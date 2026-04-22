from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol
from uuid import UUID

from shared.database.repositories.user import UserRepository
from shared.infrastructure import setup_logger
from shared.infrastructure.config import RankingParams

from ..lobby.models import Lobby, LobbyConfig, LobbyState, Seat
from ..notifier import Notifier
from .errors import QueueError
from .models import QueueEntry
from .ranker import Placement, find_best_assignment

logger = setup_logger(__name__)

UserRepoFactory = Callable[[], AbstractAsyncContextManager[UserRepository]]


class _LobbyManagerProto(Protocol):
    def mark_in_queue(self, lobby_id: UUID) -> None: ...
    def mark_idle(self, lobby_id: UUID) -> None: ...
    async def dissolve(self, lobby_id: UUID, reason: str) -> None: ...


class _GameManagerProto(Protocol):
    async def create_game(
        self,
        seats: tuple[Seat, Seat, Seat, Seat],
        config: LobbyConfig,
    ) -> UUID: ...


class QueueManager:
    def __init__(
        self,
        lobby_mgr: _LobbyManagerProto,
        game_mgr: _GameManagerProto,
        notifier: Notifier,
        user_repo_factory: UserRepoFactory,
        tick_sec: float,
        ranking: RankingParams,
    ) -> None:
        self._entries: dict[UUID, QueueEntry] = {}
        self._tick_sec = tick_sec
        self._task: asyncio.Task[None] | None = None
        self._lobby_mgr = lobby_mgr
        self._game_mgr = game_mgr
        self._notifier = notifier
        self._user_repo_factory = user_repo_factory
        self._ranking = ranking

    def get(self, lobby_id: UUID) -> QueueEntry | None:
        return self._entries.get(lobby_id)

    async def enqueue(self, lobby: Lobby) -> None:
        if lobby.id in self._entries:
            raise QueueError.already_in_queue()
        if lobby.state != LobbyState.IDLE:
            raise QueueError.bad_lobby_state()
        size = lobby.size
        if size not in (1, 2, 3, 4):
            raise QueueError.bad_lobby_size()
        if size == 3 and lobby.config.rated:
            raise QueueError.rated_three_players()

        sigmas: list[float | None] = [None, None, None, None]
        colors: list[int | None] = [None, None, None, None]
        async with self._user_repo_factory() as repo:
            for i, seat in enumerate(lobby.seats):
                if seat is None:
                    continue
                user = await repo.get_by_id(seat.user_id)
                if user is None:
                    raise QueueError.bad_lobby_state()
                sigmas[i] = user.sigma
                colors[i] = user.color

        present_mus = [s.rating for s in lobby.seats if s is not None]
        present_sigmas = [sig for sig in sigmas if sig is not None]
        avg_mu = sum(present_mus) / len(present_mus)
        avg_sigma = sum(present_sigmas) / len(present_sigmas)

        entry = QueueEntry(
            lobby_id=lobby.id,
            size=size,
            config=lobby.config,
            enqueued_at=time.monotonic(),
            seats=tuple(lobby.seats),
            sigmas=tuple(sigmas),
            colors=tuple(colors),
            avg_mu=avg_mu,
            avg_sigma=avg_sigma,
        )
        self._entries[lobby.id] = entry
        self._lobby_mgr.mark_in_queue(lobby.id)
        user_ids = [str(s.user_id) for s in lobby.seats if s is not None]
        await self._notifier.publish_queue_started(user_ids)

    async def cancel(self, lobby_id: UUID) -> None:
        entry = self._entries.pop(lobby_id, None)
        if entry is None:
            raise QueueError.not_in_queue()
        self._lobby_mgr.mark_idle(lobby_id)
        user_ids = [str(s.user_id) for s in entry.seats if s is not None]
        await self._notifier.publish_queue_cancelled(user_ids)

    def start_loop(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_loop())

    async def stop_loop(self) -> None:
        task = self._task
        if task is None:
            return
        self._task = None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("queue loop terminated with error")

    async def _run_loop(self) -> None:
        while True:
            await asyncio.sleep(self._tick_sec)
            try:
                await self._tick()
            except Exception:
                logger.exception("queue tick failed")

    async def _tick(self) -> None:
        groups: dict[tuple[bool, int, int], list[QueueEntry]] = defaultdict(list)
        for entry in self._entries.values():
            key = (entry.config.rated, entry.config.initial_ms, entry.config.increment_ms)
            groups[key].append(entry)

        now = time.monotonic()
        for group in groups.values():
            while len(group) > 0:
                best = find_best_assignment(group, now, self._ranking)
                if best is None:
                    break
                entries_chosen, placement = best
                await self._fire(entries_chosen, placement)
                for e in entries_chosen:
                    group.remove(e)

    async def _fire(
        self,
        entries: tuple[QueueEntry, ...],
        placement: Placement,
    ) -> None:
        slot_seats: list[Seat | None] = [None, None, None, None]
        user_ids: list[UUID] = []
        for entry, slot_indices in zip(entries, placement):
            positions = entry.positions
            for entry_pos, slot_idx in zip(positions, slot_indices):
                seat = entry.seats[entry_pos]
                assert seat is not None
                slot_seats[slot_idx] = seat
                user_ids.append(seat.user_id)

        seats_tuple: tuple[Seat, Seat, Seat, Seat] = (
            slot_seats[0],  # type: ignore[assignment]
            slot_seats[1],  # type: ignore[assignment]
            slot_seats[2],  # type: ignore[assignment]
            slot_seats[3],  # type: ignore[assignment]
        )
        config = entries[0].config
        game_id = await self._game_mgr.create_game(seats_tuple, config)

        str_ids = [str(uid) for uid in user_ids]
        await self._notifier.publish_match_found(str_ids, str(game_id))

        for entry in entries:
            self._entries.pop(entry.lobby_id, None)
            await self._lobby_mgr.dissolve(entry.lobby_id, "game_started")
