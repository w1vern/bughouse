
import asyncio
import json

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from redis.asyncio.client import PubSub, Redis

from shared.database import User

from ..depends import get_db_user
from ..redis import RedisType, get_redis_client
from .models import Game, Lobby, Move, State

router = APIRouter(
    prefix="/ws",
    tags=["WebSocket"]
)


async def websocket_handler(
    websocket: WebSocket,
    state: State,
    user: User,
    redis: Redis
) -> None:
    try:
        async for msg in websocket.iter_text():
            message = json.loads(msg)
            match message["type"]:
                case "ping":
                    await websocket.send_text("pong")
                case "move":
                    pass
                case _:
                    raise ValueError("Unknown message type")
    except WebSocketDisconnect:
        pass


async def redis_handler(
    state: State,
    user: User,
    ps: PubSub
) -> None:
    try:
        async for msg in ps.listen():
            if msg["type"] == "message":
                pass
    except asyncio.CancelledError:
        await ps.unsubscribe()
        await ps.close()


@router.websocket(
    path="",
    name="WebSocket"
)
async def _(
    websocket: WebSocket,
    user: User = Depends(get_db_user),
    redis: Redis = Depends(get_redis_client)
) -> None:
    await websocket.accept()
    pubsub = redis.pubsub()
    str_state = await redis.get(f"{RedisType.state.value}:{user.id}")
    if str_state is None:
        state = State()
    else:
        state = State.from_json(str_state)

    redis_task = asyncio.create_task(redis_handler(state, user, pubsub))
    websocket_task = asyncio.create_task(websocket_handler(websocket, state, user, redis))

    done, pending = await asyncio.wait(
        [redis_task, websocket_task],
        return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()
        await task
