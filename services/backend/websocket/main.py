
import asyncio
from uuid import uuid4

import grpc
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis

from shared.database import User
from shared.events import ErrorEvent, ServerEvent
from shared.infrastructure import setup_logger
from shared.protobuf import core_pb2, core_pb2_grpc

from ..depends import get_db_user
from ..redis import get_redis_client
from .dispatcher import dispatch, snapshot_from_pb
from .grpc_client import get_core_stub

logger = setup_logger(__name__)

router = APIRouter(prefix="/ws", tags=["WebSocket"])

ONLINE_KEY_PREFIX = "ws:online:"
USER_CHANNEL_PREFIX = "ws:user:"
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


async def _send_event(websocket: WebSocket, event: ServerEvent) -> None:
    await websocket.send_text(event.model_dump_json())


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


async def _send_snapshot(
    stub: core_pb2_grpc.CoreServiceStub,
    user: User,
    websocket: WebSocket,
) -> None:
    try:
        resp: core_pb2.SnapshotResp = await stub.GetUserSnapshot(
            core_pb2.UserRef(user_id=str(user.id))
        )
    except grpc.aio.AioRpcError as exc:
        logger.warning("GetUserSnapshot failed for user=%s: %s", user.id, exc)
        code = exc.code().name if exc.code() is not None else "grpc_error"
        await _send_event(
            websocket, ErrorEvent(code=code, message=exc.details() or "")
        )
        return
    await _send_event(websocket, snapshot_from_pb(resp, user.id))


async def _pubsub_loop(redis: Redis, user: User, websocket: WebSocket) -> None:
    channel = f"{USER_CHANNEL_PREFIX}{user.id}"
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
    stub: core_pb2_grpc.CoreServiceStub,
    user: User,
    websocket: WebSocket,
) -> None:
    async for raw in websocket.iter_text():
        reply = await dispatch(stub, user, raw)
        if reply is not None:
            await _send_event(websocket, reply)


@router.websocket(path="")
async def websocket_endpoint(
    websocket: WebSocket,
    user: User = Depends(get_db_user),
    redis: Redis = Depends(get_redis_client),
    stub: core_pb2_grpc.CoreServiceStub = Depends(get_core_stub),
) -> None:
    await websocket.accept()
    logger.debug("connected")

    key = f"{ONLINE_KEY_PREFIX}{user.id}"
    conn_uuid = uuid4().hex
    acquired = await redis.set(key, conn_uuid, nx=True, ex=LOCK_TTL_SEC)
    if not acquired:
        await websocket.close(code=4409, reason="already_connected")
        return

    await _send_snapshot(stub, user, websocket)

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
            await redis.eval(_RELEASE_LOCK_LUA, 1, key, conn_uuid)
        except Exception:
            logger.exception("failed to release ws:online lock")
        try:
            await redis.aclose()
        except Exception:
            pass
