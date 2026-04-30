from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from redis.asyncio import Redis

from shared.events import (
    GameEnd,
    GameMoveEvent,
    GameStart,
    LobbyDeleted,
    LobbyStateEvent,
    QueueCancelled,
    QueueMatchFound,
    QueueStarted,
    ServerEvent,
)
from shared.events.common import (
    BoardPocketsPayload,
    ClocksPayload,
    EndReasonStr,
    GameResultStr,
    LobbyConfigPayload,
    PocketsPayload,
    SeatPayload,
)
from shared.infrastructure import setup_logger

from .game.models import EndReason, GameObj, GameResult, MoveRecord
from .lobby.models import Lobby, LobbyState

logger = setup_logger(__name__)


def _seats_payload(lobby: Lobby) -> list[SeatPayload | None]:
    out: list[SeatPayload | None] = []
    for seat in lobby.seats:
        if seat is None:
            out.append(None)
        else:
            out.append(SeatPayload(
                user_id=str(seat.user_id),
                username=seat.username,
                rating=seat.rating,
            ))
    return out


def _lobby_state_str(lobby: Lobby) -> str:
    return "in_queue" if lobby.state == LobbyState.IN_QUEUE else "idle"


def _lobby_config_payload(lobby: Lobby) -> LobbyConfigPayload:
    return LobbyConfigPayload(
        initial_ms=lobby.config.initial_ms,
        increment_ms=lobby.config.increment_ms,
        rated=lobby.config.rated,
    )


def _build_lobby_state_event(lobby: Lobby, your_pos: int) -> LobbyStateEvent:
    return LobbyStateEvent(
        id=str(lobby.id),
        leader_id=str(lobby.leader_id),
        seats=_seats_payload(lobby),
        config=_lobby_config_payload(lobby),
        state=_lobby_state_str(lobby),  # type: ignore[arg-type]
        your_pos=your_pos,
    )


def _board_pockets(raw: dict[str, dict[str, int]]) -> BoardPocketsPayload:
    return BoardPocketsPayload.model_validate(raw)


def pockets_from_raw(raw: dict[str, dict[str, dict[str, int]]]) -> PocketsPayload:
    return PocketsPayload(
        b0=_board_pockets(raw.get("b0", {"w": {}, "b": {}})),
        b1=_board_pockets(raw.get("b1", {"w": {}, "b": {}})),
    )


def clocks_from_raw(raw: dict[str, int]) -> ClocksPayload:
    return ClocksPayload(
        b0w=raw["b0w"], b0b=raw["b0b"], b1w=raw["b1w"], b1b=raw["b1b"]
    )


def result_str(result: GameResult) -> GameResultStr:
    mapping: dict[GameResult, GameResultStr] = {
        GameResult.TEAM_A: "team_a",
        GameResult.TEAM_B: "team_b",
        GameResult.DRAW: "draw",
        GameResult.ABORT: "abort",
    }
    return mapping[result]


def reason_str(reason: EndReason) -> EndReasonStr:
    return reason.value  # type: ignore[return-value]


class Notifier:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def publish(self, user_id: str | UUID, event: ServerEvent) -> None:
        channel = f"ws:user:{user_id}"
        message = event.model_dump_json()
        logger.debug("redis publish -> channel=%s event=%s", channel, event.type)
        try:
            await self._redis.publish(channel, message)
        except Exception:
            logger.exception("Failed to publish %s to %s", event.type, channel)

    async def _fanout(
        self,
        user_ids: Iterable[str | UUID],
        event: ServerEvent,
    ) -> None:
        for uid in user_ids:
            await self.publish(uid, event)

    async def publish_lobby_state(self, lobby: Lobby) -> None:
        seated = [s.user_id for s in lobby.seats if s is not None]
        logger.debug("publish_lobby_state: lobby_id=%s state=%s recipients=%s", lobby.id, lobby.state, seated)
        for pos, seat in enumerate(lobby.seats):
            if seat is None:
                continue
            await self.publish(seat.user_id, _build_lobby_state_event(lobby, pos))

    async def publish_lobby_deleted(
        self,
        user_ids: Iterable[str | UUID],
        reason: str,
    ) -> None:
        ids = list(user_ids)
        logger.debug("publish_lobby_deleted: reason=%s recipients=%s", reason, ids)
        await self._fanout(ids, LobbyDeleted(reason=reason))

    async def publish_queue_started(self, user_ids: Iterable[str | UUID]) -> None:
        ids = list(user_ids)
        logger.debug("publish_queue_started: recipients=%s", ids)
        await self._fanout(ids, QueueStarted())

    async def publish_queue_cancelled(self, user_ids: Iterable[str | UUID]) -> None:
        ids = list(user_ids)
        logger.debug("publish_queue_cancelled: recipients=%s", ids)
        await self._fanout(ids, QueueCancelled())

    async def publish_match_found(
        self,
        user_ids: Iterable[str | UUID],
        game_id: str,
    ) -> None:
        ids = list(user_ids)
        logger.debug("publish_match_found: game_id=%s recipients=%s", game_id, ids)
        await self._fanout(ids, QueueMatchFound(game_id=game_id))

    async def publish_game_start(
        self,
        game: GameObj,
        per_user_events: dict[str, GameStart],
    ) -> None:
        logger.debug("publish_game_start: game_id=%s recipients=%s", game.id, game.user_ids)
        for uid in game.user_ids:
            await self.publish(uid, per_user_events[uid])

    async def publish_move(self, game: GameObj, event: GameMoveEvent) -> None:
        logger.debug("publish_move: game_id=%s uci=%s recipients=%s", game.id, event.uci, game.user_ids)
        await self._fanout(game.user_ids, event)

    async def publish_game_end(self, game: GameObj, event: GameEnd) -> None:
        logger.debug("publish_game_end: game_id=%s result=%s reason=%s recipients=%s", game.id, event.result, event.reason, game.user_ids)
        await self._fanout(game.user_ids, event)
