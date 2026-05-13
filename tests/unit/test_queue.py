from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from uuid import UUID, uuid4

import chess

from services.core.game.models import pos_to_color
from services.core.lobby.manager import LobbyManager
from services.core.lobby.models import (
    Lobby,
    LobbyConfig,
    LobbyState,
    Seat
)
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
from services.core.queue.ranker import (
    compose_teams,
    find_best_assignment
)
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
        config=config or LobbyConfig(clock_time=60_000, incr=1_000),
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
        self.in_game: list[UUID] = []
        self._lobbies: dict[UUID, Lobby] = {}

    def register(self, lobby: Lobby) -> None:
        self._lobbies[lobby.id] = lobby

    def get(self, lobby_id: UUID) -> Lobby | None:
        return self._lobbies.get(lobby_id)

    def mark_in_queue(self, lobby_id: UUID) -> None:
        self.in_queue.append(lobby_id)

    def mark_idle(self, lobby_id: UUID) -> None:
        self.idle.append(lobby_id)

    def mark_in_game(self, lobby_id: UUID) -> None:
        self.in_game.append(lobby_id)


class FakeGameManager:
    def __init__(self) -> None:
        self.created: list[
            tuple[
                tuple[Seat, Seat, Seat, Seat],
                LobbyConfig,
                bool,
                tuple[UUID | None, UUID | None, UUID | None, UUID | None],
            ]
        ] = []

    async def create_game(
        self,
        seats: tuple[Seat, Seat, Seat, Seat],
        config: LobbyConfig,
        *,
        color_flip: bool = False,
        lobby_ids: tuple[UUID | None, UUID | None, UUID | None, UUID | None] = (
            None, None, None, None,
        ),
    ) -> UUID:
        self.created.append((seats, config, color_flip, lobby_ids))
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


def _placement_game_positions(placement: tuple[tuple[int, int, int, int], ...]) -> list[int]:
    return sorted(p for mapping in placement for p in mapping if p != -1)


class QueueEntryTests(unittest.TestCase):
    def test_positions_returns_only_occupied_lobby_slots(self) -> None:
        entry = make_entry(["alice", None, "carol", None])

        self.assertEqual(entry.positions, (0, 2))


class QueueRankerTests(unittest.TestCase):
    def test_compose_teams_uses_new_team_layout(self) -> None:
        slots = tuple(Seat(username=name, rating=25.0) for name in ("a", "b", "c", "d"))

        team_a, team_b = compose_teams(slots)  # type: ignore[arg-type]

        # Team A = (slot 0, slot 1) = leader + partner.
        # Team B = (slot 2, slot 3) = leader's opp + partner's opp.
        self.assertEqual([seat.username for seat in team_a], ["a", "b"])
        self.assertEqual([seat.username for seat in team_b], ["c", "d"])

    def test_find_best_assignment_returns_none_until_four_players_are_available(self) -> None:
        entry = make_entry(["alice", None, None, None])

        self.assertIsNone(find_best_assignment([entry], now=10.0, params=ranking_params()))

    def test_find_best_assignment_can_fill_game_from_two_pairs(self) -> None:
        first = make_entry(["alice", "bob", None, None])    # teammates
        second = make_entry([None, None, "carol", "dave"])  # teammates

        result = find_best_assignment([first, second], now=10.0, params=ranking_params())

        self.assertIsNotNone(result)
        entries, placement, _color_flip = result
        self.assertEqual(entries, (first, second))
        self.assertEqual(_placement_game_positions(placement), [0, 1, 2, 3])
        # First entry (lobby slots 0,1 = teammates) must occupy a teammate pair in game.
        first_positions = sorted(p for p in placement[0] if p != -1)
        self.assertIn(first_positions, ([0, 1], [2, 3]))
        # Second entry (slots 2,3) must occupy the other teammate pair.
        second_positions = sorted(p for p in placement[1] if p != -1)
        self.assertIn(second_positions, ([0, 1], [2, 3]))
        self.assertNotEqual(first_positions, second_positions)

    def test_find_best_assignment_preserves_opponent_topology_for_cross_team_pair(self) -> None:
        # Two players in lobby slots (0, 2) — leader + leader's same-board opp.
        first = make_entry(["alice", None, "bob", None])
        second = make_entry([None, "carol", None, "dave"])

        result = find_best_assignment([first, second], now=10.0, params=ranking_params())

        self.assertIsNotNone(result)
        _entries, placement, _flip = result
        first_pair = sorted(p for p in placement[0] if p != -1)
        # Same-board-opp pairs in game: (0,2) and (1,3).
        self.assertIn(first_pair, ([0, 2], [1, 3]))

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

    def test_find_best_assignment_prefers_colors_that_reduce_player_imbalance(self) -> None:
        entry = make_entry(["alice", "bob", "carol", "dave"])
        entry.colors = (1, -1, -1, 1)

        result = find_best_assignment([entry], now=10.0, params=ranking_params())

        self.assertIsNotNone(result)
        _entries, placement, color_flip = result
        leader_game_pos = placement[0][0]
        self.assertEqual(pos_to_color(leader_game_pos, color_flip), chess.BLACK)

    def test_bounded_assignment_prioritizes_oldest_anchor(self) -> None:
        entries = [
            make_entry(
                [f"player_{idx}", None, None, None],
                enqueued_at=1.0,
            )
            for idx in range(100)
        ]
        oldest = make_entry(["oldest", None, None, None], enqueued_at=0.0)
        group = [oldest, *entries]

        result = find_best_assignment(
            group,
            now=10.0,
            params=ranking_params(),
            exact_entry_limit=1,
            nearest_candidate_limit=12,
        )

        self.assertIsNotNone(result)
        assert result is not None
        chosen, _placement, _flip = result
        self.assertIn(oldest.lobby_id, [entry.lobby_id for entry in chosen])

    def test_bounded_assignment_keeps_two_pair_matches(self) -> None:
        first = make_entry(["alice", "bob", None, None])
        second = make_entry([None, None, "carol", "dave"])

        result = find_best_assignment(
            [first, second],
            now=10.0,
            params=ranking_params(),
            exact_entry_limit=1,
        )

        self.assertIsNotNone(result)
        assert result is not None
        chosen, placement, _flip = result
        self.assertEqual(
            {entry.lobby_id for entry in chosen},
            {first.lobby_id, second.lobby_id},
        )
        self.assertEqual(_placement_game_positions(placement), [0, 1, 2, 3])

    def test_bounded_assignment_prefers_three_plus_one_before_solos(self) -> None:
        solo = make_entry(["solo", None, None, None], enqueued_at=0.0)
        trio = make_entry(["a", "b", "c", None], enqueued_at=1.0)
        extra_solos = [
            make_entry([name, None, None, None], enqueued_at=1.0)
            for name in ("d", "e", "f")
        ]

        result = find_best_assignment(
            [solo, trio, *extra_solos],
            now=10.0,
            params=ranking_params(),
            exact_entry_limit=1,
        )

        self.assertIsNotNone(result)
        assert result is not None
        chosen, _placement, _flip = result
        self.assertEqual(
            {entry.lobby_id for entry in chosen},
            {solo.lobby_id, trio.lobby_id},
        )

    def test_bounded_assignment_prefers_pair_plus_two_solos_before_solos(self) -> None:
        solo = make_entry(["solo", None, None, None], enqueued_at=0.0)
        pair = make_entry(["a", "b", None, None], enqueued_at=1.0)
        extra_solos = [
            make_entry([name, None, None, None], enqueued_at=1.0)
            for name in ("c", "d", "e")
        ]

        result = find_best_assignment(
            [solo, pair, *extra_solos],
            now=10.0,
            params=ranking_params(),
            exact_entry_limit=1,
        )

        self.assertIsNotNone(result)
        assert result is not None
        chosen, _placement, _flip = result
        self.assertIn(solo.lobby_id, [entry.lobby_id for entry in chosen])
        self.assertIn(pair.lobby_id, [entry.lobby_id for entry in chosen])
        self.assertEqual(sum(entry.size for entry in chosen), 4)


class QueueManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        names = [
            "alice",
            "bob",
            "carol",
            "dave",
            "erin",
            "frank",
            "gina",
            "hank",
        ]
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
        self.assertEqual(self.manager.queued_lobbies_count, 1)
        self.assertEqual(self.manager.queued_players_count, 1)
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
        self.lobby_mgr.register(lobby)
        await self.manager.enqueue(lobby)

        await self.manager.cancel(lobby.id)

        self.assertIsNone(self.manager.get(lobby.id))
        self.assertEqual(self.manager.queued_lobbies_count, 0)
        self.assertEqual(self.manager.queued_players_count, 0)
        self.assertEqual(self.lobby_mgr.idle, [lobby.id])
        self.assertEqual(self.notifier.cancelled, [lobby.id])

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

    async def test_tick_creates_game_and_marks_lobbies_in_game(self) -> None:
        lobbies = [
            make_lobby([name, None, None, None])
            for name in ("alice", "bob", "carol", "dave")
        ]
        for lobby in lobbies:
            await self.manager.enqueue(lobby)

        await self.manager._do_tick()

        # Lobbies are no longer in the queue but they survived (in-game).
        self.assertEqual([self.manager.get(lobby.id) for lobby in lobbies], [None] * 4)
        self.assertEqual(
            sorted(self.lobby_mgr.in_game),
            sorted(lobby.id for lobby in lobbies),
        )
        self.assertEqual(len(self.game_mgr.created), 1)
        seats, config, _color_flip, lobby_ids = self.game_mgr.created[0]
        self.assertEqual(sorted(seat.username for seat in seats), list(PLAYER_NAMES_SORTED))
        # Each game position remembers which lobby it came from.
        self.assertEqual(set(lobby_ids), {lobby.id for lobby in lobbies})
        self.assertIs(config, lobbies[0].config)

    async def test_tick_does_not_match_lobbies_with_different_configs(self) -> None:
        fast = LobbyConfig(clock_time=60_000, incr=1_000, rated=False)
        slow = LobbyConfig(clock_time=120_000, incr=1_000, rated=False)
        first = make_lobby(["alice", "bob", None, None], config=fast)
        second = make_lobby([None, None, "carol", "dave"], config=slow)
        await self.manager.enqueue(first)
        await self.manager.enqueue(second)

        await self.manager._do_tick()

        self.assertEqual(self.game_mgr.created, [])
        self.assertIsNotNone(self.manager.get(first.id))
        self.assertIsNotNone(self.manager.get(second.id))

    async def test_tick_starts_complete_lobbies_before_config_grouping(self) -> None:
        fast = LobbyConfig(clock_time=60_000, incr=1_000, rated=False)
        slow = LobbyConfig(clock_time=120_000, incr=1_000, rated=True)
        first = make_lobby(["alice", "bob", "carol", "dave"], config=fast)
        second = make_lobby(["erin", "frank", "gina", "hank"], config=slow)
        await self.manager.enqueue(first)
        await self.manager.enqueue(second)

        await self.manager._do_tick()

        self.assertIsNone(self.manager.get(first.id))
        self.assertIsNone(self.manager.get(second.id))
        self.assertEqual(len(self.game_mgr.created), 2)
        created_configs = [created[1] for created in self.game_mgr.created]
        self.assertIn(fast, created_configs)
        self.assertIn(slow, created_configs)

    async def test_start_and_stop_loop_are_idempotent(self) -> None:
        self.manager.start_loop()
        first_task = self.manager._task

        self.manager.start_loop()

        self.assertIs(self.manager._task, first_task)
        await self.manager.stop_loop()
        self.assertIsNone(self.manager._task)


PLAYER_NAMES_SORTED = sorted(("alice", "bob", "carol", "dave"))


if __name__ == "__main__":
    unittest.main()
