from __future__ import annotations

import time
from dataclasses import dataclass
from uuid import UUID

from redis.asyncio import Redis

from shared.infrastructure import setup_logger

from .config import Config
from .game.manager import GameManager
from .lobby.errors import LobbyError
from .lobby.manager import LobbyManager
from .lobby.models import LobbyState
from .notifier import ONLINE_KEY_PREFIX, Notifier

logger = setup_logger(__name__)


@dataclass(slots=True)
class Invite:
    sender: str
    receiver: str
    lobby_id: UUID
    idx: int
    expires_at: float


class InviteManager:
    def __init__(
        self,
        lobbies: LobbyManager,
        games: GameManager,
        notifier: Notifier,
        redis: Redis,
        ttl: float = Config.invite_ttl,
    ) -> None:
        self._invites: dict[tuple[str, str], Invite] = {}
        self._lobbies = lobbies
        self._games = games
        self._notifier = notifier
        self._redis = redis
        self._ttl = ttl

    async def send(self, sender: str, receiver: str, idx: int) -> None:
        if sender == receiver:
            raise LobbyError.invite_self()
        if idx not in (0, 1, 2, 3):
            raise LobbyError.seat_out_of_range()

        lobby = self._lobbies.get_by_user(sender)
        if lobby is None:
            raise LobbyError.user_not_in_lobby()
        if lobby.leader != sender:
            raise LobbyError.not_leader()
        if lobby.state != LobbyState.IDLE:
            raise LobbyError.cannot_modify_while_in_queue()
        if lobby.seats[idx] is not None:
            raise LobbyError.seat_occupied()

        if self._lobbies.get_by_user(receiver) is not None:
            raise LobbyError.invite_target_busy()
        if self._games.get_game_by_user(receiver) is not None:
            raise LobbyError.invite_target_busy()

        if not await self._is_online(receiver):
            raise LobbyError.invite_target_offline()

        self._invites[(sender, receiver)] = Invite(
            sender=sender,
            receiver=receiver,
            lobby_id=lobby.id,
            idx=idx,
            expires_at=time.monotonic() + self._ttl / 1000,
        )
        await self._notifier.publish_invite_receive(receiver, sender, idx)

    async def accept(self, receiver: str, sender: str) -> UUID:
        invite = self._take(sender, receiver)
        try:
            await self._lobbies.join_at(
                invite.lobby_id, receiver, invite.idx
            )
        except LobbyError:
            raise
        # All other invites for this receiver are now stale (user is busy).
        self._cleanup_for_user(receiver)
        return invite.lobby_id

    async def reject(self, receiver: str, sender: str) -> None:
        invite = self._take(sender, receiver)
        lobby = self._lobbies.get(invite.lobby_id)
        if lobby is not None:
            await self._notifier.publish_invite_rejected(
                lobby, invite.idx, receiver
            )

    def cleanup_for_lobby(self, lobby_id: UUID) -> None:
        keys = [k for k, inv in self._invites.items() if inv.lobby_id ==
                lobby_id]
        for k in keys:
            self._invites.pop(k, None)

    def cleanup_for_user(self, username: str) -> None:
        self._cleanup_for_user(username)

    # ---------------- Internals ----------------

    def _cleanup_for_user(self, username: str) -> None:
        keys = [
            k for k, inv in self._invites.items()
            if inv.sender == username or inv.receiver == username
        ]
        for k in keys:
            self._invites.pop(k, None)

    def _take(self, sender: str, receiver: str) -> Invite:
        invite = self._invites.pop((sender, receiver), None)
        if invite is None:
            raise LobbyError.invite_not_found()
        if invite.expires_at < time.monotonic():
            raise LobbyError.invite_not_found()
        return invite

    async def _is_online(self, username: str) -> bool:
        try:
            return bool(await self._redis.exists(f"{ONLINE_KEY_PREFIX}{username}"))
        except Exception:
            logger.exception("ws:online check failed for %s", username)
            return False
