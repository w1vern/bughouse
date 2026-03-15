
import json

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from redis.asyncio.client import PubSub, Redis

from shared.database import User

from ..depends import get_db_user
from ..redis import get_redis_client

router = APIRouter(
    prefix="/ws",
    tags=["WebSocket"]
)


async def websocket_handler(
    websocket: WebSocket,
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
    user: User,
    ps: PubSub
) -> None:
    async for msg in ps.listen():
        if msg["type"] == "message":
            pass


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

    try:
        pass
    except Exception:
        pass
    finally:
        pass
