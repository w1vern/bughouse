from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from uuid import UUID, uuid4

from services.core.lobby.manager import LobbyManager
from services.core.lobby.models import Lobby, LobbyConfig, LobbyState, Seat
from services.core.queue.errors import (
    ERR_ALREADY_IN_QUEUE,
    ERR_BAD_LOBBY_SIZE,
    ERR_BAD_LOBBY_STATE,
    ERR_NOT_IN_QUEUE,
    ERR_RATED_THREE_PLAYERS,
    QueueError,
)
from services.core.queue.manager import QueueManager
from services.core.queue.models import QueueEntry
from services.core.queue.ranker import compose_teams, find_best_assignment
from shared.infrastructure import RankingParams


def ranking_params() -> RankingParams:
    return RankingParams(
        mu=25.0,
        sigma=8.333,
        beta=4.166,
        tau=0.083,
        epsilon=0.0,
        queue_wait_bonus=0.001,
        queue_color_weight=0.01,
    )


def make_user(
    username: str,
    *,
    rating: float = 25.0,
    sigma: float = 8.333,
    color: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        username=username,
        rating=rating,
        sigma=sigma,
        color=color,
    )


def make_lobby(
    usernames: list[str | None],
    *,
    config: LobbyConfig | None = None,
    state: LobbyState = LobbyState.IDLE,
    ratings: dict[str, float] | None = None,
) -> Lobby:
    rating_by_name = ratings or {}
    seats = [
        Seat(username=name, rating=rating_by_name.get(name, 25.0))
        if name is not None
        else None
        for name in usernames
    ]
    leader = next(seat.username for seat in seats if seat is not None)
    return Lobby(
        id=uuid4(),
        leader=leader,
        seats=seats,
        config=config or LobbyConfig(initial_ms=60_000, increment_ms=1_000),
        state=state,
    )


def make_entry(
    usernames: list[str | None],
    *,
    config: LobbyConfig | None = None,
    enqueued_at: float = 0.0,
    color: int = 0,
) -> QueueEntry:
    lobby = make_lobby(usernames, config=config)
    sigmas = tuple(8.333 if seat is not None else None for seat in lobby.seats)
    colors = tuple(color if seat is not None else None for seat in lobby.seats)
    present = [seat for seat in lobby.seats if seat is not None]
    return QueueEntry(
        lobby_id=lobby.id,
        size=len(present),
        config=lobby.config,
        enqueued_at=enqueued_at,
        seats=tuple(lobby.seats),
        sigmas=sigmas,
        colors=colors,
        avg_mu=sum(seat.rating for seat in present) / len(present),
        avg_sigma=8.333,
    )


class FakeUserRepoFactory:
    def __init__(self, users: dict[str, SimpleNamespace]) -> None:
        self.users = users

    def __call__(self) -> FakeUserRepoFactory:
        return self

    async def __aenter__(self) -> FakeUserRepoFactory:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def get_by_username(self, username: str) -> SimpleNamespace | None:
        return self.users.get(username)


class FakeLobbyManager:
    def __init__(self) -> None:
        self.in_queue: list[UUID] = []
        self.idle: list[UUID] = []
        self.dissolved: list[UUID] = []

    def mark_in_queue(self, lobby_id: UUID) -> None:
        self.in_queue.append(lobby_id)

    def mark_idle(self, lobby_id: UUID) -> None:
        self.idle.append(lobby_id)

    async def dissolve(self, lobby_id: UUID) -> None:
        self.dissolved.append(lobby_id)


class FakeGameManager:
    def __init__(self) -> None:
        self.created: list[tuple[tuple[Seat, Seat, Seat, Seat], LobbyConfig]] = []

    async def create_game(
        self,
        seats: tuple[Seat, Seat, Seat, Seat],
        config: LobbyConfig,
    ) -> UUID:
        self.created.append((seats, config))
        return uuid4()


class FakeNotifier:
    def __init__(self) -> None:
        self.started: list[UUID] = []
        self.cancelled: list[UUID] = []
        self.busy: list[str] = []
        self.idle: list[str] = []

    async def publish_queue_started(self, lobby: Lobby) -> None:
        self.started.append(lobby.id)

    async def publish_queue_cancelled(self, lobby: Lobby) -> None:
        self.cancelled.append(lobby.id)

    async def mark_busy(self, username: str) -> None:
        self.busy.append(username)

    async def mark_idle_if_online(self, username: str) -> None:
        self.idle.append(username)


class QueueEntryTests(unittest.TestCase):
    def test_positions_returns_only_occupied_lobby_slots(self) -> None:
        entry = make_entry(["alice", None, "carol", None])

        self.assertEqual(entry.positions, (0, 2))


class QueueRankerTests(unittest.TestCase):
    def test_compose_teams_uses_bughouse_team_layout(self) -> None:
        slots = tuple(Seat(username=name, rating=25.0) for name in ("a", "b", "c", "d"))

        team_a, team_b = compose_teams(slots)  # type: ignore[arg-type]

        self.assertEqual([seat.username for seat in team_a], ["a", "d"])
        self.assertEqual([seat.username for seat in team_b], ["b", "c"])

    def test_find_best_assignment_returns_none_until_four_players_are_available(self) -> None:
        entry = make_entry(["alice", None, None, None])

        self.assertIsNone(find_best_assignment([entry], now=10.0, params=ranking_params()))

    def test_find_best_assignment_can_fill_game_from_two_pairs(self) -> None:
        first = make_entry(["alice", "bob", None, None])
        second = make_entry([None, None, "carol", "dave"])

        result = find_best_assignment([first, second], now=10.0, params=ranking_params())

        self.assertIsNotNone(result)
        entries, placement = result
        self.assertEqual(entries, (first, second))
        self.assertEqual(tuple(len(slots) for slots in placement), (2, 2))
        self.assertEqual(sorted(slot for slots in placement for slot in slots), [0, 1, 2, 3])

    def test_find_best_assignment_allows_three_plus_one_only_for_unrated_games(self) -> None:
        unrated_cfg = LobbyConfig(rated=False)
        rated_cfg = LobbyConfig(rated=True)
        unrated_three = make_entry(["a", "b", "c", None], config=unrated_cfg)
        unrated_one = make_entry(["d", None, None, None], config=unrated_cfg)
        rated_three = make_entry(["e", "f", "g", None], config=rated_cfg)
        rated_one = make_entry(["h", None, None, None], config=rated_cfg)

        self.assertIsNotNone(
            find_best_assignment(
                [unrated_three, unrated_one],
                now=10.0,
                params=ranking_params(),
            )
        )
        self.assertIsNone(
            find_best_assignment(
                [rated_three, rated_one],
                now=10.0,
                params=ranking_params(),
            )
        )


class QueueManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        names = ["alice", "bob", "carol", "dave", "erin", "frank"]
        self.users = {name: make_user(name) for name in names}
        self.user_repo_factory = FakeUserRepoFactory(self.users)
        self.lobby_mgr = FakeLobbyManager()
        self.game_mgr = FakeGameManager()
        self.notifier = FakeNotifier()
        self.manager = QueueManager(
            lobby_mgr=self.lobby_mgr,  # type: ignore[arg-type]
            game_mgr=self.game_mgr,  # type: ignore[arg-type]
            notifier=self.notifier,  # type: ignore[arg-type]
            user_repo_factory=self.user_repo_factory,  # type: ignore[arg-type]
            tick=999_000.0,
            ranking=ranking_params(),
        )

    async def asyncTearDown(self) -> None:
        await self.manager.stop_loop()

    async def test_enqueue_adds_entry_and_marks_lobby_in_queue(self) -> None:
        self.users["alice"].sigma = 7.0
        self.users["alice"].color = -3
        lobby = make_lobby(["alice", None, None, None], ratings={"alice": 31.0})

        await self.manager.enqueue(lobby)

        entry = self.manager.get(lobby.id)
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.size, 1)
        self.assertEqual(entry.avg_mu, 31.0)
        self.assertEqual(entry.avg_sigma, 7.0)
        self.assertEqual(entry.sigmas, (7.0, None, None, None))
        self.assertEqual(entry.colors, (-3, None, None, None))
        self.assertEqual(self.lobby_mgr.in_queue, [lobby.id])
        self.assertEqual(self.notifier.started, [lobby.id])

    async def test_enqueue_rejects_duplicate_lobby(self) -> None:
        lobby = make_lobby(["alice", None, None, None])
        await self.manager.enqueue(lobby)

        with self.assertRaises(QueueError) as error:
            await self.manager.enqueue(lobby)

        self.assertEqual(error.exception.code, ERR_ALREADY_IN_QUEUE)

    async def test_enqueue_rejects_bad_lobby_state_and_size(self) -> None:
        queued_lobby = make_lobby(
            ["alice", None, None, None],
            state=LobbyState.IN_QUEUE,
        )
        empty_lobby = make_lobby(["alice", None, None, None])
        empty_lobby.seats = [None, None, None, None]

        with self.assertRaises(QueueError) as state_error:
            await self.manager.enqueue(queued_lobby)
        with self.assertRaises(QueueError) as size_error:
            await self.manager.enqueue(empty_lobby)

        self.assertEqual(state_error.exception.code, ERR_BAD_LOBBY_STATE)
        self.assertEqual(size_error.exception.code, ERR_BAD_LOBBY_SIZE)
        self.assertEqual(self.notifier.started, [])

    async def test_enqueue_rejects_rated_three_player_lobby(self) -> None:
        lobby = make_lobby(
            ["alice", "bob", "carol", None],
            config=LobbyConfig(rated=True),
        )

        with self.assertRaises(QueueError) as error:
            await self.manager.enqueue(lobby)

        self.assertEqual(error.exception.code, ERR_RATED_THREE_PLAYERS)
        self.assertIsNone(self.manager.get(lobby.id))

    async def test_enqueue_rejects_lobby_when_user_data_is_missing(self) -> None:
        self.users.pop("bob")
        lobby = make_lobby(["alice", "bob", None, None])

        with self.assertRaises(QueueError) as error:
            await self.manager.enqueue(lobby)

        self.assertEqual(error.exception.code, ERR_BAD_LOBBY_STATE)
        self.assertIsNone(self.manager.get(lobby.id))
        self.assertEqual(self.lobby_mgr.in_queue, [])

    async def test_cancel_removes_entry_and_marks_lobby_idle(self) -> None:
        lobby = make_lobby(["alice", None, None, None])
        await self.manager.enqueue(lobby)

        await self.manager.cancel(lobby.id)

        self.assertIsNone(self.manager.get(lobby.id))
        self.assertEqual(self.lobby_mgr.idle, [lobby.id])

    async def test_cancel_rejects_lobby_that_is_not_queued(self) -> None:
        with self.assertRaises(QueueError) as error:
            await self.manager.cancel(uuid4())

        self.assertEqual(error.exception.code, ERR_NOT_IN_QUEUE)

    async def test_cancel_publishes_when_used_with_real_lobby_manager(self) -> None:
        lobby = make_lobby(["alice", None, None, None])
        lobby_mgr = LobbyManager(
            notifier=self.notifier,  # type: ignore[arg-type]
            user_repo_factory=self.user_repo_factory,  # type: ignore[arg-type]
        )
        lobby_mgr._lobbies[lobby.id] = lobby
        lobby_mgr._user_to_lobby["alice"] = lobby.id
        manager = QueueManager(
            lobby_mgr=lobby_mgr,
            game_mgr=self.game_mgr,  # type: ignore[arg-type]
            notifier=self.notifier,  # type: ignore[arg-type]
            user_repo_factory=self.user_repo_factory,  # type: ignore[arg-type]
            tick=999_000.0,
            ranking=ranking_params(),
        )
        try:
            await manager.enqueue(lobby)
            await manager.cancel(lobby.id)
        finally:
            await manager.stop_loop()

        self.assertEqual(self.notifier.cancelled, [lobby.id])
        self.assertEqual(lobby.state, LobbyState.IDLE)

    async def test_tick_creates_game_and_dissolves_matched_lobbies(self) -> None:
        lobbies = [
            make_lobby([name, None, None, None])
            for name in ("alice", "bob", "carol", "dave")
        ]
        for lobby in lobbies:
            await self.manager.enqueue(lobby)

        await self.manager._do_tick()

        self.assertEqual([self.manager.get(lobby.id) for lobby in lobbies], [None] * 4)
        self.assertEqual(self.lobby_mgr.dissolved, [lobby.id for lobby in lobbies])
        self.assertEqual(len(self.game_mgr.created), 1)
        seats, config = self.game_mgr.created[0]
        self.assertEqual([seat.username for seat in seats], ["alice", "bob", "carol", "dave"])
        self.assertIs(config, lobbies[0].config)

    async def test_tick_does_not_match_lobbies_with_different_configs(self) -> None:
        fast = LobbyConfig(initial_ms=60_000, increment_ms=1_000, rated=False)
        slow = LobbyConfig(initial_ms=120_000, increment_ms=1_000, rated=False)
        first = make_lobby(["alice", "bob", None, None], config=fast)
        second = make_lobby([None, None, "carol", "dave"], config=slow)
        await self.manager.enqueue(first)
        await self.manager.enqueue(second)

        await self.manager._do_tick()

        self.assertEqual(self.game_mgr.created, [])
        self.assertIsNotNone(self.manager.get(first.id))
        self.assertIsNotNone(self.manager.get(second.id))

    async def test_start_and_stop_loop_are_idempotent(self) -> None:
        self.manager.start_loop()
        first_task = self.manager._task

        self.manager.start_loop()

        self.assertIs(self.manager._task, first_task)
        await self.manager.stop_loop()
        self.assertIsNone(self.manager._task)


if __name__ == "__main__":
    unittest.main()
