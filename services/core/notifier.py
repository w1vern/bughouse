from __future__ import annotations

import time
from collections.abc import Iterable

from redis.asyncio import Redis

from shared.events import (
    BughouseData,
    CamelModel,
    ClocksData,
    ErrorData,
    ErrorMsg,
    GameChatData,
    GameChatReceiveMsg,
    GameEndData,
    GameEndMsg,
    GameJoinMsg,
    GameMoveReceiveMsg,
    GameMoveServerData,
    GameStatus,
    InviteData,
    InviteReceiveMsg,
    InviteRejectedData,
    LobbyCancelMMMsg,
    LobbyConfigUpdateMsg,
    LobbyData,
    LobbyInviteRejectedMsg,
    LobbyJoinMsg,
    LobbyKickedMsg,
    LobbyPlayerJoinMsg,
    LobbyPlayerLeaveData,
    LobbyPlayerLeaveMsg,
    LobbyPlayerSlot,
    LobbyStartMMMsg,
    LobbyTimeRatingData,
    LobbyUpdateSlot,
    SyncData,
    SyncMsg,
    dump,
)
from shared.infrastructure import setup_logger

from .game.models import EndReason, GameObj, GameResult
from .lobby.models import Lobby, LobbyState, Seat

logger = setup_logger(__name__)


def _slot_payload(seat: Seat | None) -> LobbyPlayerSlot | None:
    if seat is None:
        return None
    return LobbyPlayerSlot(username=seat.username, rating=seat.rating)


def lobby_data(lobby: Lobby) -> LobbyData:
    return LobbyData(
        clock_time=lobby.config.clock_time,
        incr=lobby.config.incr,
        rated=lobby.config.rated,
        in_queue=lobby.state == LobbyState.IN_QUEUE,
        slots=[_slot_payload(s) for s in lobby.seats],
        leader=lobby.leader,
    )


def sync_for_lobby(lobby: Lobby) -> SyncData:
    return SyncData(state="LOBBY", lobby=lobby_data(lobby), game=None)


def sync_idle() -> SyncData:
    return SyncData(state="IDLE", lobby=None, game=None)


def lobby_config_payload(lobby: Lobby) -> LobbyTimeRatingData:
    return LobbyTimeRatingData(
        clock_time=lobby.config.clock_time,
        incr=lobby.config.incr,
        rated=lobby.config.rated,
    )


def clocks_payload(snap: dict[str, int]) -> ClocksData:
    return ClocksData(
        b0w=snap["b0w"], b0b=snap["b0b"], b1w=snap["b1w"], b1b=snap["b1b"]
    )


_RESULT_TO_STATUS: dict[GameResult, GameStatus] = {
    GameResult.TEAM_A: "WinA",
    GameResult.TEAM_B: "WinB",
    GameResult.DRAW: "Draw",
    GameResult.ABORT: "Abort",
}


def result_status(result: GameResult) -> GameStatus:
    return _RESULT_TO_STATUS[result]


def reason_str(reason: EndReason) -> str:
    return reason.value


ACTIVE_SET_KEY = "active_player"
ONLINE_KEY_PREFIX = "ws:online:"


class Notifier:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def _send(self, username: str, msg: CamelModel) -> None:
        channel = f"ws:user:{username}"
        payload = dump(msg)
        try:
            await self._redis.publish(channel, payload)
        except Exception:
            logger.exception("Failed to publish to %s", channel)

    # ------------- Active-set bookkeeping -------------

    async def _is_online(self, username: str) -> bool:
        try:
            return bool(await self._redis.exists(f"{ONLINE_KEY_PREFIX}{username}"))
        except Exception:
            logger.exception("ws:online check failed for %s", username)
            return False

    async def mark_busy(self, username: str) -> None:
        try:
            await self._redis.srem(ACTIVE_SET_KEY, username)  # type: ignore[misc]
        except Exception:
            logger.exception("active_player SREM failed for %s", username)

    async def mark_idle_if_online(self, username: str) -> None:
        if not await self._is_online(username):
            return
        try:
            await self._redis.sadd(ACTIVE_SET_KEY, username)  # type: ignore[misc]
        except Exception:
            logger.exception("active_player SADD failed for %s", username)

    async def _fanout(
        self,
        usernames: Iterable[str],
        msg: CamelModel,
        *,
        exclude: str | None = None,
    ) -> None:
        for u in usernames:
            if u == exclude:
                continue
            await self._send(u, msg)

    # ------------- Lobby -------------

    async def publish_lobby_join(self, lobby: Lobby, username: str) -> None:
        await self._send(username, LobbyJoinMsg(data=lobby_data(lobby)))

    async def publish_lobby_full_state(self, lobby: Lobby) -> None:
        msg = LobbyJoinMsg(data=lobby_data(lobby))
        await self._fanout(lobby.usernames, msg)

    async def publish_player_slot_update(
        self,
        lobby: Lobby,
        idx: int,
        seat: Seat | None,
        *,
        exclude: str | None = None,
    ) -> None:
        msg = LobbyPlayerJoinMsg(
            data=LobbyUpdateSlot(idx=idx, slot=_slot_payload(seat))  # type: ignore[arg-type]
        )
        for u in lobby.usernames:
            if u == exclude:
                continue
            await self._send(u, msg)

    async def publish_player_leave(
        self,
        lobby: Lobby,
        idx: int,
        reason: str,
    ) -> None:
        msg = LobbyPlayerLeaveMsg(
            data=LobbyPlayerLeaveData(idx=idx, reason=reason)  # type: ignore[arg-type]
        )
        await self._fanout(lobby.usernames, msg)

    async def publish_lobby_kicked(self, username: str) -> None:
        await self._send(username, LobbyKickedMsg())

    async def publish_lobby_config(self, lobby: Lobby) -> None:
        msg = LobbyConfigUpdateMsg(data=lobby_config_payload(lobby))
        await self._fanout(lobby.usernames, msg)

    # ------------- Invites -------------

    async def publish_invite_receive(
        self,
        receiver: str,
        sender: str,
        idx: int,
    ) -> None:
        msg = InviteReceiveMsg(
            data=InviteData(idx=idx, username=sender)  # type: ignore[arg-type]
        )
        await self._send(receiver, msg)

    async def publish_invite_rejected(
        self,
        lobby: Lobby,
        idx: int,
        rejecter: str,
    ) -> None:
        msg = LobbyInviteRejectedMsg(
            data=InviteRejectedData(idx=idx, username=rejecter)  # type: ignore[arg-type]
        )
        await self._fanout(lobby.usernames, msg)

    # ------------- Queue -------------

    async def publish_queue_started(self, lobby: Lobby) -> None:
        await self._fanout(lobby.usernames, LobbyStartMMMsg())

    async def publish_queue_cancelled(self, lobby: Lobby) -> None:
        await self._fanout(lobby.usernames, LobbyCancelMMMsg())

    # ------------- Game -------------

    async def publish_game_start(
        self,
        usernames: Iterable[str],
        bughouse: BughouseData,
    ) -> None:
        msg = GameJoinMsg(data=bughouse)
        await self._fanout(usernames, msg)

    async def publish_move(
        self,
        usernames: Iterable[str],
        idx: int,
        uci: str,
        white_clock_time: int,
        black_clock_time: int,
        auto_abort_at: int | None,
        *,
        exclude: str | None = None,
    ) -> None:
        msg = GameMoveReceiveMsg(
            data=GameMoveServerData(
                idx=idx,  # type: ignore[arg-type]
                move=uci,
                white_clock_time=white_clock_time,
                black_clock_time=black_clock_time,
                auto_abort_at=auto_abort_at,
            )
        )
        await self._fanout(usernames, msg, exclude=exclude)

    async def publish_game_chat(self, username: str, message: GameChatData) -> None:
        await self._send(username, GameChatReceiveMsg(data=message))

    async def publish_game_end(
        self,
        usernames: Iterable[str],
        status: GameStatus,
        rating_changes: dict[str, float],
    ) -> None:
        msg = GameEndMsg(
            data=GameEndData(status=status, rating_changes=rating_changes)
        )
        await self._fanout(usernames, msg)

    async def publish_back_to_lobby(self, username: str, lobby: Lobby) -> None:
        await self._send(username, SyncMsg(data=sync_for_lobby(lobby)))

    async def publish_back_to_idle(self, username: str) -> None:
        await self._send(username, SyncMsg(data=sync_idle()))

    # ------------- Direct -------------

    async def send_error(self, username: str, code: str, message: str = "") -> None:
        await self._send(
            username,
            ErrorMsg(data=ErrorData(code=code, message=message or None)),
        )

    async def send_sync(self, username: str, sync: SyncData) -> None:
        await self._send(username, SyncMsg(data=sync))


def now() -> int:
    return int(time.time() * 1000)
