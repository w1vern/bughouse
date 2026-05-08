
import asyncio
from uuid import uuid4

import grpc
from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    WebSocket,
    WebSocketDisconnect
)
from redis.asyncio import Redis

from shared.database import User, UserRepository, session_manager
from shared.events import (
    CamelModel,
    ErrorData,
    ErrorMsg,
    SyncData,
    SyncMsg,
    dump,
)
from shared.infrastructure import setup_logger
from shared.protobuf import core_pb2

from ..depends import get_user
from ..exceptions import SendFeedbackToAdminException
from ..redis import RedisType, get_redis_client
from .dispatcher import dispatch
from .grpc_client import AsyncCoreServiceStub, get_core_stub

logger = setup_logger(__name__)

router = APIRouter(prefix="/ws", tags=["WebSocket"])

ONLINE_KEY_PREFIX = "ws:online:"
USER_CHANNEL_PREFIX = "ws:user:"
ACTIVE_SET_KEY = RedisType.active_player.value
LOCK_TTL_SEC = 30
LOCK_REFRESH_SEC = 10

_RELEASE_LOCK_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
else
  return 0
end
"""

_REFRESH_LOCK_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('pexpire', KEYS[1], ARGV[2])
else
  return 0
end
"""


async def _send(websocket: WebSocket, msg: CamelModel) -> None:
    await websocket.send_text(dump(msg))


async def _refresh_lock_loop(redis: Redis, key: str, conn_uuid: str) -> None:
    try:
        while True:
            await asyncio.sleep(LOCK_REFRESH_SEC)
            ok = await redis.eval(
                _REFRESH_LOCK_LUA, 1, key, conn_uuid, LOCK_TTL_SEC * 1000,
            )
            if not ok:
                logger.warning("lost ws:online lock for key=%s", key)
                return
    except asyncio.CancelledError:
        raise


async def _send_initial_sync(
    stub: AsyncCoreServiceStub,
    user: User,
    websocket: WebSocket,
    redis: Redis,
) -> None:
    try:
        resp: core_pb2.SnapshotResp = await stub.GetUserSnapshot(
            core_pb2.UserRef(username=user.username)
        )
    except grpc.aio.AioRpcError as exc:
        logger.warning("GetUserSnapshot failed for user=%s: %s", user.username, exc)
        code = exc.code().name if exc.code() is not None else "grpc_error"
        await _send(
            websocket, ErrorMsg(data=ErrorData(code=code, message=exc.details() or ""))
        )
        return
    if not resp.ok:
        await _send(
            websocket,
            ErrorMsg(
                data=ErrorData(
                    code=resp.error_code or "snapshot_failed",
                    message=resp.message or "",
                )
            ),
        )
        return
    sync = SyncData.model_validate_json(resp.sync_json)
    await _send(websocket, SyncMsg(data=sync))

    # Add to active set only when user is idle (no lobby/game).
    if sync.state == "IDLE":
        try:
            await redis.sadd(ACTIVE_SET_KEY, user.username)  # type: ignore[misc]
        except Exception:
            logger.exception("active_player SADD failed")


async def _pubsub_loop(redis: Redis, user: User, websocket: WebSocket) -> None:
    channel = f"{USER_CHANNEL_PREFIX}{user.username}"
    pubsub = redis.pubsub()
    try:
        await pubsub.subscribe(channel)
        async for msg in pubsub.listen():
            if msg.get("type") != "message":
                continue
            data = msg.get("data")
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            if isinstance(data, str):
                await websocket.send_text(data)
    except asyncio.CancelledError:
        raise
    finally:
        try:
            await pubsub.unsubscribe(channel)
        except Exception:
            pass
        try:
            await pubsub.aclose()
        except Exception:
            pass


async def _client_loop(
    stub: AsyncCoreServiceStub,
    user: User,
    websocket: WebSocket,
) -> None:
    async for raw in websocket.iter_text():
        reply = await dispatch(stub, user, raw)
        if reply is not None:
            await _send(websocket, reply)


async def get_ws_db_user(
    access_token: str | None = Cookie(default=None),
    redis: Redis = Depends(get_redis_client),
) -> User:
    token_user = await get_user(access_token=access_token, redis=redis)
    async with session_manager.context_session() as session:
        repo = UserRepository(session)
        user_db = await repo.get_by_id(token_user.id)
    if user_db is None:
        raise SendFeedbackToAdminException()
    return user_db


@router.websocket(path="")
async def websocket_endpoint(
    websocket: WebSocket,
    user: User = Depends(get_ws_db_user),
    redis: Redis = Depends(get_redis_client),
    stub: AsyncCoreServiceStub = Depends(get_core_stub),
) -> None:
    await websocket.accept()
    logger.debug("ws connected: %s", user.username)

    key = f"{ONLINE_KEY_PREFIX}{user.username}"
    conn_uuid = uuid4().hex
    acquired = await redis.set(key, conn_uuid, nx=True, ex=LOCK_TTL_SEC)
    if not acquired:
        await websocket.close(code=4409, reason="already_connected")
        return

    await _send_initial_sync(stub, user, websocket, redis)

    tasks: list[asyncio.Task[None]] = [
        asyncio.create_task(_refresh_lock_loop(redis, key, conn_uuid), name="ws-refresh"),
        asyncio.create_task(_pubsub_loop(redis, user, websocket), name="ws-pubsub"),
        asyncio.create_task(_client_loop(stub, user, websocket), name="ws-client"),
    ]

    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in pending:
            try:
                await task
            except (asyncio.CancelledError, WebSocketDisconnect):
                pass
            except Exception:
                logger.exception("error while cancelling ws task")
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, (WebSocketDisconnect, asyncio.CancelledError)):
                logger.exception("ws task %s failed", task.get_name(), exc_info=exc)
    finally:
        try:
            await redis.srem(ACTIVE_SET_KEY, user.username)  # type: ignore[misc]
        except Exception:
            logger.exception("active_player SREM failed")
        try:
            await redis.eval(_RELEASE_LOCK_LUA, 1, key, conn_uuid)
        except Exception:
            logger.exception("failed to release ws:online lock")
        try:
            await redis.aclose()
        except Exception:
            pass
