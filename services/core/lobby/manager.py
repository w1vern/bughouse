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
        self._user_to_lobby: dict[str, UUID] = {}
        self._notifier = notifier
        self._user_repo_factory = user_repo_factory

    # ---------------- Queries ----------------

    def get(self, lobby_id: UUID) -> Lobby | None:
        return self._lobbies.get(lobby_id)

    def get_by_user(self, username: str) -> Lobby | None:
        lobby_id = self._user_to_lobby.get(username)
        if lobby_id is None:
            return None
        return self._lobbies.get(lobby_id)

    # ---------------- Mutations ----------------

    async def create(self, username: str, config: LobbyConfig | None = None) -> Lobby:
        if username in self._user_to_lobby:
            raise LobbyError.user_already_in_lobby()
        cfg = config or LobbyConfig()
        self._validate_config(cfg)
        seat = await self._load_seat(username)
        lobby = Lobby(
            id=uuid4(),
            leader=username,
            seats=[seat, None, None, None],
            config=cfg,
            state=LobbyState.IDLE,
        )
        self._lobbies[lobby.id] = lobby
        self._user_to_lobby[username] = lobby.id
        await self._notifier.mark_busy(username)
        await self._notifier.publish_lobby_join(lobby, username)
        return lobby

    async def join_at(
        self,
        lobby_id: UUID,
        username: str,
        idx: int,
    ) -> Lobby:
        lobby = self._require_lobby(lobby_id)
        self._ensure_mutable(lobby)
        if username in self._user_to_lobby:
            raise LobbyError.user_already_in_lobby()
        if idx not in (0, 1, 2, 3):
            raise LobbyError.seat_out_of_range()
        if lobby.seats[idx] is not None:
            raise LobbyError.seat_occupied()
        seat = await self._load_seat(username)
        lobby.seats[idx] = seat
        self._user_to_lobby[username] = lobby.id
        await self._notifier.mark_busy(username)
        await self._notifier.publish_lobby_join(lobby, username)
        await self._notifier.publish_player_slot_update(
            lobby, idx, seat, exclude=username,
        )
        return lobby

    async def leave(self, username: str, *, kicked: bool = False) -> Lobby | None:
        lobby_id = self._user_to_lobby.get(username)
        if lobby_id is None:
            raise LobbyError.user_not_in_lobby()
        lobby = self._require_lobby(lobby_id)
        self._ensure_mutable(lobby)
        pos = lobby.seat_of(username)
        if pos is None:
            raise LobbyError.user_not_in_lobby()
        lobby.seats[pos] = None
        self._user_to_lobby.pop(username, None)
        await self._notifier.mark_idle_if_online(username)

        if kicked:
            await self._notifier.publish_lobby_kicked(username)

        if lobby.size == 0:
            del self._lobbies[lobby.id]
            return None

        new_leader = False
        if lobby.leader == username:
            self._assign_new_leader(lobby)
            new_leader = True

        await self._notifier.publish_player_leave(
            lobby, pos, "kick" if kicked else "leave",
        )
        if new_leader:
            await self._notifier.publish_lobby_full_state(lobby)
        return lobby

    async def kick(self, leader_username: str, target: str) -> Lobby | None:
        lobby_id = self._user_to_lobby.get(leader_username)
        if lobby_id is None:
            raise LobbyError.user_not_in_lobby()
        lobby = self._require_lobby(lobby_id)
        self._ensure_mutable(lobby)
        self._ensure_leader(lobby, leader_username)
        if target == leader_username:
            raise LobbyError.cannot_kick_self()
        if lobby.seat_of(target) is None:
            raise LobbyError.target_not_in_lobby()
        return await self.leave(target, kicked=True)

    async def set_config(
        self,
        leader_username: str,
        cfg: LobbyConfig,
    ) -> Lobby:
        lobby_id = self._user_to_lobby.get(leader_username)
        if lobby_id is None:
            raise LobbyError.user_not_in_lobby()
        lobby = self._require_lobby(lobby_id)
        self._ensure_mutable(lobby)
        self._ensure_leader(lobby, leader_username)
        self._validate_config(cfg)
        lobby.config = cfg
        await self._notifier.publish_lobby_config(lobby)
        return lobby

    # ---------------- State transitions ----------------

    def mark_in_queue(self, lobby_id: UUID) -> None:
        lobby = self._require_lobby(lobby_id)
        lobby.state = LobbyState.IN_QUEUE

    def mark_idle(self, lobby_id: UUID) -> None:
        lobby = self._require_lobby(lobby_id)
        lobby.state = LobbyState.IDLE

    async def dissolve(self, lobby_id: UUID) -> None:
        lobby = self._lobbies.pop(lobby_id, None)
        if lobby is None:
            return
        for username in lobby.usernames:
            self._user_to_lobby.pop(username, None)
            await self._notifier.mark_idle_if_online(username)

    # ---------------- Internals ----------------

    def _require_lobby(self, lobby_id: UUID) -> Lobby:
        lobby = self._lobbies.get(lobby_id)
        if lobby is None:
            raise LobbyError.not_found()
        return lobby

    def _ensure_mutable(self, lobby: Lobby) -> None:
        if lobby.state == LobbyState.IN_QUEUE:
            raise LobbyError.cannot_modify_while_in_queue()

    def _ensure_leader(self, lobby: Lobby, username: str) -> None:
        if lobby.leader != username:
            raise LobbyError.not_leader()

    def _assign_new_leader(self, lobby: Lobby) -> None:
        for s in lobby.seats:
            if s is not None:
                lobby.leader = s.username
                return

    def _validate_config(self, cfg: LobbyConfig) -> None:
        if cfg.clock_time <= 0:
            raise LobbyError.bad_config("clock_time must be positive")
        if cfg.incr < 0:
            raise LobbyError.bad_config("incr must be non-negative")

    async def _load_seat(self, username: str) -> Seat:
        async with self._user_repo_factory() as repo:
            user = await repo.get_by_username(username)
        if user is None:
            raise LobbyError.user_not_found()
        return Seat(username=user.username, rating=user.rating)
