from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from redis.asyncio import Redis

from shared.infrastructure import setup_logger

from .game.models import GameObj
from .lobby.models import Lobby, LobbyState

logger = setup_logger(__name__)


def _seats_payload(lobby: Lobby) -> list[dict[str, Any] | None]:
    out: list[dict[str, Any] | None] = []
    for seat in lobby.seats:
        if seat is None:
            out.append(None)
        else:
            out.append({
                "user_id": str(seat.user_id),
                "username": seat.username,
                "rating": seat.rating,
            })
    return out


def _lobby_state_str(lobby: Lobby) -> str:
    return "in_queue" if lobby.state == LobbyState.IN_QUEUE else "idle"


def _lobby_payload(lobby: Lobby, your_pos: int | None) -> dict[str, Any]:
    return {
        "id": str(lobby.id),
        "leader_id": str(lobby.leader_id),
        "seats": _seats_payload(lobby),
        "config": {
            "initial_ms": lobby.config.initial_ms,
            "increment_ms": lobby.config.increment_ms,
            "rated": lobby.config.rated,
        },
        "state": _lobby_state_str(lobby),
        "your_pos": your_pos,
    }


class Notifier:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def publish(
        self,
        user_id: str | UUID,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        channel = f"ws:user:{user_id}"
        message = json.dumps({"type": event_type, **payload}, ensure_ascii=False)
        try:
            await self._redis.publish(channel, message)
        except Exception:
            logger.exception("Failed to publish %s to %s", event_type, channel)

    async def _fanout(
        self,
        user_ids: Iterable[str | UUID],
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        for uid in user_ids:
            await self.publish(uid, event_type, payload)

    async def publish_lobby_state(self, lobby: Lobby) -> None:
        for pos, seat in enumerate(lobby.seats):
            if seat is None:
                continue
            await self.publish(
                seat.user_id,
                "lobby.state",
                _lobby_payload(lobby, your_pos=pos),
            )

    async def publish_lobby_deleted(
        self,
        user_ids: Iterable[str | UUID],
        reason: str,
    ) -> None:
        await self._fanout(user_ids, "lobby.deleted", {"reason": reason})

    async def publish_queue_started(self, user_ids: Iterable[str | UUID]) -> None:
        await self._fanout(user_ids, "queue.started", {})

    async def publish_queue_cancelled(self, user_ids: Iterable[str | UUID]) -> None:
        await self._fanout(user_ids, "queue.cancelled", {})

    async def publish_match_found(
        self,
        user_ids: Iterable[str | UUID],
        game_id: str,
    ) -> None:
        await self._fanout(user_ids, "queue.match_found", {"game_id": game_id})

    async def publish_game_start(
        self,
        game: GameObj,
        per_user_payload: dict[str, dict[str, Any]],
    ) -> None:
        for uid in game.user_ids:
            await self.publish(uid, "game.start", per_user_payload[uid])

    async def publish_move(self, game: GameObj, payload: dict[str, Any]) -> None:
        await self._fanout(game.user_ids, "game.move", payload)

    async def publish_game_end(self, game: GameObj, payload: dict[str, Any]) -> None:
        await self._fanout(game.user_ids, "game.end", payload)

    async def publish_error(
        self,
        user_id: str | UUID,
        code: str,
        message: str,
    ) -> None:
        await self.publish(user_id, "error", {"code": code, "message": message})
