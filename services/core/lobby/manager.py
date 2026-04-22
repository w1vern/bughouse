from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from uuid import UUID, uuid4

from shared.database.repositories.user import UserRepository
from shared.infrastructure import setup_logger

from ..notifier import Notifier
from .errors import LobbyError
from .models import Lobby, LobbyConfig, LobbyState, Seat

logger = setup_logger(__name__)

UserRepoFactory = Callable[[], AbstractAsyncContextManager[UserRepository]]


class LobbyManager:
    def __init__(
        self,
        notifier: Notifier,
        user_repo_factory: UserRepoFactory,
    ) -> None:
        self._lobbies: dict[UUID, Lobby] = {}
        self._user_to_lobby: dict[UUID, UUID] = {}
        self._notifier = notifier
        self._user_repo_factory = user_repo_factory

    # ---------------- Queries ----------------

    def get(self, lobby_id: UUID) -> Lobby | None:
        return self._lobbies.get(lobby_id)

    def get_by_user(self, user_id: UUID) -> Lobby | None:
        lobby_id = self._user_to_lobby.get(user_id)
        if lobby_id is None:
            return None
        return self._lobbies.get(lobby_id)

    # ---------------- Mutations ----------------

    async def create(self, user_id: UUID) -> Lobby:
        if user_id in self._user_to_lobby:
            raise LobbyError.user_already_in_lobby()
        seat = await self._load_seat(user_id)
        lobby = Lobby(
            id=uuid4(),
            leader_id=user_id,
            seats=[seat, None, None, None],
            config=LobbyConfig(),
            state=LobbyState.IDLE,
        )
        self._lobbies[lobby.id] = lobby
        self._user_to_lobby[user_id] = lobby.id
        await self._notifier.publish_lobby_state(lobby)
        return lobby

    async def join(self, lobby_id: UUID, user_id: UUID) -> Lobby:
        lobby = self._require_lobby(lobby_id)
        self._ensure_mutable(lobby)
        if user_id in self._user_to_lobby:
            raise LobbyError.user_already_in_lobby()
        free_pos = self._first_free_slot(lobby)
        if free_pos is None:
            raise LobbyError.lobby_full()
        seat = await self._load_seat(user_id)
        lobby.seats[free_pos] = seat
        self._user_to_lobby[user_id] = lobby.id
        await self._notifier.publish_lobby_state(lobby)
        return lobby

    async def leave(self, lobby_id: UUID, user_id: UUID) -> Lobby | None:
        lobby = self._require_lobby(lobby_id)
        self._ensure_mutable(lobby)
        pos = lobby.seat_of(user_id)
        if pos is None:
            raise LobbyError.user_not_in_lobby()
        lobby.seats[pos] = None
        self._user_to_lobby.pop(user_id, None)

        if lobby.size == 0:
            del self._lobbies[lobby.id]
            await self._notifier.publish_lobby_deleted([user_id], "empty")
            return None

        if lobby.leader_id == user_id:
            self._assign_new_leader(lobby)
        await self._notifier.publish_lobby_state(lobby)
        return lobby

    async def seat(
        self,
        lobby_id: UUID,
        leader_id: UUID,
        target_user_id: UUID,
        pos: int,
    ) -> Lobby:
        lobby = self._require_lobby(lobby_id)
        self._ensure_mutable(lobby)
        self._ensure_leader(lobby, leader_id)
        if pos not in (1, 2, 3):
            raise LobbyError.seat_out_of_range()
        current = lobby.seat_of(target_user_id)
        if current is None:
            raise LobbyError.target_not_in_lobby()
        if current == pos:
            return lobby
        if lobby.seats[pos] is not None:
            raise LobbyError.seat_occupied()
        lobby.seats[pos] = lobby.seats[current]
        lobby.seats[current] = None
        await self._notifier.publish_lobby_state(lobby)
        return lobby

    async def unseat(self, lobby_id: UUID, leader_id: UUID, pos: int) -> Lobby:
        lobby = self._require_lobby(lobby_id)
        self._ensure_mutable(lobby)
        self._ensure_leader(lobby, leader_id)
        if pos not in (1, 2, 3):
            raise LobbyError.seat_out_of_range()
        occupant = lobby.seats[pos]
        if occupant is None:
            raise LobbyError.user_not_in_lobby()
        lobby.seats[pos] = None
        self._user_to_lobby.pop(occupant.user_id, None)
        await self._notifier.publish_lobby_state(lobby)
        return lobby

    async def kick(
        self,
        lobby_id: UUID,
        leader_id: UUID,
        target_user_id: UUID,
    ) -> Lobby:
        lobby = self._require_lobby(lobby_id)
        self._ensure_mutable(lobby)
        self._ensure_leader(lobby, leader_id)
        if target_user_id == leader_id:
            raise LobbyError.cannot_kick_self()
        pos = lobby.seat_of(target_user_id)
        if pos is None:
            raise LobbyError.target_not_in_lobby()
        lobby.seats[pos] = None
        self._user_to_lobby.pop(target_user_id, None)
        await self._notifier.publish_lobby_state(lobby)
        return lobby

    async def set_config(
        self,
        lobby_id: UUID,
        leader_id: UUID,
        cfg: LobbyConfig,
    ) -> Lobby:
        lobby = self._require_lobby(lobby_id)
        self._ensure_mutable(lobby)
        self._ensure_leader(lobby, leader_id)
        self._validate_config(cfg)
        lobby.config = cfg
        await self._notifier.publish_lobby_state(lobby)
        return lobby

    # ---------------- State transitions ----------------

    def mark_in_queue(self, lobby_id: UUID) -> None:
        lobby = self._require_lobby(lobby_id)
        lobby.state = LobbyState.IN_QUEUE

    def mark_idle(self, lobby_id: UUID) -> None:
        lobby = self._require_lobby(lobby_id)
        lobby.state = LobbyState.IDLE

    async def dissolve(self, lobby_id: UUID, reason: str) -> None:
        lobby = self._lobbies.pop(lobby_id, None)
        if lobby is None:
            return
        user_ids = lobby.user_ids
        for uid in user_ids:
            self._user_to_lobby.pop(uid, None)
        await self._notifier.publish_lobby_deleted(user_ids, reason)

    # ---------------- Internals ----------------

    def _require_lobby(self, lobby_id: UUID) -> Lobby:
        lobby = self._lobbies.get(lobby_id)
        if lobby is None:
            raise LobbyError.not_found()
        return lobby

    def _ensure_mutable(self, lobby: Lobby) -> None:
        if lobby.state == LobbyState.IN_QUEUE:
            raise LobbyError.cannot_modify_while_in_queue()

    def _ensure_leader(self, lobby: Lobby, user_id: UUID) -> None:
        if lobby.leader_id != user_id:
            raise LobbyError.not_leader()

    def _first_free_slot(self, lobby: Lobby) -> int | None:
        for i, s in enumerate(lobby.seats):
            if s is None:
                return i
        return None

    def _assign_new_leader(self, lobby: Lobby) -> None:
        for s in lobby.seats:
            if s is not None:
                lobby.leader_id = s.user_id
                return

    def _validate_config(self, cfg: LobbyConfig) -> None:
        if cfg.initial_ms <= 0:
            raise LobbyError.bad_config("initial_ms must be positive")
        if cfg.increment_ms < 0:
            raise LobbyError.bad_config("increment_ms must be non-negative")

    async def _load_seat(self, user_id: UUID) -> Seat:
        async with self._user_repo_factory() as repo:
            user = await repo.get_by_id(user_id)
        if user is None:
            raise LobbyError.user_not_found()
        return Seat(user_id=user.id, username=user.username, rating=user.rating)
