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
    def get(self, lobby_id: UUID) -> Lobby | None: ...
    def mark_in_queue(self, lobby_id: UUID) -> None: ...
    def mark_idle(self, lobby_id: UUID) -> None: ...
    def mark_in_game(self, lobby_id: UUID) -> None: ...


class _GameManagerProto(Protocol):
    async def create_game(
        self,
        seats: tuple[Seat, Seat, Seat, Seat],
        config: LobbyConfig,
        *,
        color_flip: bool = False,
        lobby_ids: tuple[UUID | None, UUID | None, UUID | None, UUID | None] = (
            None, None, None, None,
        ),
    ) -> UUID: ...


class QueueManager:
    def __init__(
        self,
        lobby_mgr: _LobbyManagerProto,
        game_mgr: _GameManagerProto,
        notifier: Notifier,
        user_repo_factory: UserRepoFactory,
        tick: float,
        ranking: RankingParams,
    ) -> None:
        self._entries: dict[UUID, QueueEntry] = {}
        self._tick = tick
        self._task: asyncio.Task[None] | None = None
        self._lobby_mgr = lobby_mgr
        self._game_mgr = game_mgr
        self._notifier = notifier
        self._user_repo_factory = user_repo_factory
        self._ranking = ranking

    def get(self, lobby_id: UUID) -> QueueEntry | None:
        return self._entries.get(lobby_id)

    @property
    def queued_lobbies_count(self) -> int:
        return len(self._entries)

    @property
    def queued_players_count(self) -> int:
        return sum(entry.size for entry in self._entries.values())

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
                user = await repo.get_by_username(seat.username)
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
        await self._notifier.publish_queue_started(lobby)

    async def cancel(self, lobby_id: UUID) -> None:
        entry = self._entries.pop(lobby_id, None)
        if entry is None:
            raise QueueError.not_in_queue()
        self._lobby_mgr.mark_idle(lobby_id)
        lobby = self._lobby_mgr.get(lobby_id)
        if lobby is not None:
            await self._notifier.publish_queue_cancelled(lobby)

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
            await asyncio.sleep(self._tick / 1000)
            try:
                await self._do_tick()
            except Exception:
                logger.exception("queue tick failed")

    async def _do_tick(self) -> None:
        now = time.monotonic()
        await self._fire_complete_lobbies(now)

        groups: dict[tuple[bool, int, int], list[QueueEntry]] = defaultdict(list)
        for entry in self._entries.values():
            if entry.size == 4:
                continue
            key = (entry.config.rated, entry.config.clock_time, entry.config.incr)
            groups[key].append(entry)

        for group in groups.values():
            while len(group) > 0:
                best = find_best_assignment(group, now, self._ranking)
                if best is None:
                    break
                entries_chosen, placement, color_flip = best
                await self._fire(entries_chosen, placement, color_flip)
                for e in entries_chosen:
                    group.remove(e)

    async def _fire_complete_lobbies(self, now: float) -> None:
        """Start full 4-player lobbies before grouped matchmaking.

        A complete lobby already has all seats and its own config, so it is
        never compared with other queued lobbies.  The ranker is called with
        the single entry only to pick the best topology automorphism and
        color flip.
        """
        complete_entries = sorted(
            (entry for entry in self._entries.values() if entry.size == 4),
            key=lambda entry: (entry.enqueued_at, str(entry.lobby_id)),
        )
        for entry in complete_entries:
            if entry.lobby_id not in self._entries:
                continue
            best = find_best_assignment([entry], now, self._ranking)
            if best is None:
                logger.warning(
                    "complete queued lobby %s produced no assignment",
                    entry.lobby_id,
                )
                continue
            entries_chosen, placement, color_flip = best
            await self._fire(entries_chosen, placement, color_flip)

    async def _fire(
        self,
        entries: tuple[QueueEntry, ...],
        placement: Placement,
        color_flip: bool,
    ) -> None:
        slot_seats: list[Seat | None] = [None, None, None, None]
        slot_lobby_ids: list[UUID | None] = [None, None, None, None]
        for entry, mapping in zip(entries, placement):
            for lobby_pos in range(4):
                game_pos = mapping[lobby_pos]
                if game_pos == -1:
                    continue
                seat = entry.seats[lobby_pos]
                if seat is None:
                    continue
                slot_seats[game_pos] = seat
                slot_lobby_ids[game_pos] = entry.lobby_id

        seats_tuple: tuple[Seat, Seat, Seat, Seat] = (
            slot_seats[0],  # type: ignore[assignment]
            slot_seats[1],  # type: ignore[assignment]
            slot_seats[2],  # type: ignore[assignment]
            slot_seats[3],  # type: ignore[assignment]
        )
        lobby_ids_tuple: tuple[UUID | None, UUID | None, UUID | None, UUID | None] = (
            slot_lobby_ids[0],
            slot_lobby_ids[1],
            slot_lobby_ids[2],
            slot_lobby_ids[3],
        )

        config = entries[0].config

        for entry in entries:
            self._entries.pop(entry.lobby_id, None)
            self._lobby_mgr.mark_in_game(entry.lobby_id)

        await self._game_mgr.create_game(
            seats_tuple,
            config,
            color_flip=color_flip,
            lobby_ids=lobby_ids_tuple,
        )
