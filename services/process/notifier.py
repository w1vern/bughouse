from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Protocol

from redis.asyncio import Redis

from shared.infrastructure import setup_logger

logger = setup_logger(__name__)


class _LobbyView(Protocol):
    id: str
    leader_id: str
    user_ids: list[str]


class _GameView(Protocol):
    game_id: str
    user_ids: list[str]


class Notifier:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def publish(self, user_id: str, event_type: str, payload: dict[str, Any]) -> None:
        channel = f"ws:user:{user_id}"
        message = json.dumps({"type": event_type, **payload})
        try:
            await self._redis.publish(channel, message)
        except Exception:
            logger.exception("Failed to publish %s to %s", event_type, channel)

    async def _fanout(self, user_ids: Iterable[str], event_type: str, payload: dict[str, Any]) -> None:
        for uid in user_ids:
            await self.publish(uid, event_type, payload)

    async def publish_lobby_state(self, lobby: _LobbyView, lobby_payload: dict[str, Any]) -> None:
        await self._fanout(lobby.user_ids, "lobby.state", lobby_payload)

    async def publish_lobby_deleted(self, user_ids: Iterable[str], reason: str) -> None:
        await self._fanout(user_ids, "lobby.deleted", {"reason": reason})

    async def publish_queue_started(self, user_ids: Iterable[str]) -> None:
        await self._fanout(user_ids, "queue.started", {})

    async def publish_queue_cancelled(self, user_ids: Iterable[str]) -> None:
        await self._fanout(user_ids, "queue.cancelled", {})

    async def publish_match_found(self, user_ids: Iterable[str], game_id: str) -> None:
        await self._fanout(user_ids, "queue.match_found", {"game_id": game_id})

    async def publish_game_start(self, game: _GameView, per_user_payload: dict[str, dict[str, Any]]) -> None:
        for uid in game.user_ids:
            await self.publish(uid, "game.start", per_user_payload[uid])

    async def publish_move(self, game: _GameView, payload: dict[str, Any]) -> None:
        await self._fanout(game.user_ids, "game.move", payload)

    async def publish_game_end(self, game: _GameView, payload: dict[str, Any]) -> None:
        await self._fanout(game.user_ids, "game.end", payload)

    async def publish_error(self, user_id: str, code: str, message: str) -> None:
        await self.publish(user_id, "error", {"code": code, "message": message})
