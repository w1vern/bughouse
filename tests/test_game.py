from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import chess

import services.core.game.manager as game_manager_module
from services.core.game.board import BughouseBoards
from services.core.game.errors import (
    ERR_ILLEGAL_MOVE,
    ERR_NOT_YOUR_TURN,
    GameError,
)
from services.core.game.manager import GameManager
from services.core.game.models import EndReason, GameObj, GameResult, PlayerRef
from services.core.lobby.models import LobbyConfig, Seat
from services.core.session import UserSessionIndex
from shared.events import BughouseData
from shared.infrastructure import RankingParams


PLAYER_NAMES = ("alice", "bob", "carol", "dave")


def make_user(username: str, *, rating: float = 25.0, sigma: float = 8.333) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        username=username,
        rating=rating,
        sigma=sigma,
        color=0,
    )


class FakeSessionFactory:
    def __init__(self, users: dict[str, SimpleNamespace]) -> None:
        self.users = users
        self.created_games: list[dict[str, object]] = []
        self.commits = 0

    def __call__(self) -> FakeSessionFactory:
        return self

    async def __aenter__(self) -> FakeSessionFactory:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


class FakeUserRepository:
    def __init__(self, session: FakeSessionFactory) -> None:
        self._session = session

    async def get_by_username(self, username: str) -> SimpleNamespace | None:
        return self._session.users.get(username)


class FakeGameRepository:
    def __init__(self, session: FakeSessionFactory) -> None:
        self._session = session

    async def create(
        self,
        *,
        result: int,
        game_time: float,
        increment: float,
        users: tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace, SimpleNamespace],
        diffs: tuple[float, float, float, float],
        moves: list[tuple[str, float, int, object]],
    ) -> SimpleNamespace:
        payload = {
            "result": result,
            "game_time": game_time,
            "increment": increment,
            "users": tuple(u.username for u in users),
            "diffs": diffs,
            "moves": moves,
        }
        self._session.created_games.append(payload)
        return SimpleNamespace(id=uuid4())


class FakeNotifier:
    def __init__(self) -> None:
        self.busy: list[str] = []
        self.idle: list[str] = []
        self.game_starts: list[tuple[list[str], BughouseData]] = []
        self.moves: list[tuple[list[str], int, str, int, int]] = []
        self.game_ends: list[tuple[list[str], str, dict[str, float]]] = []

    async def mark_busy(self, username: str) -> None:
        self.busy.append(username)

    async def mark_idle_if_online(self, username: str) -> None:
        await asyncio.sleep(0)
        self.idle.append(username)

    async def publish_game_start(self, usernames: list[str], bughouse: BughouseData) -> None:
        self.game_starts.append((list(usernames), bughouse))

    async def publish_move(
        self,
        usernames: list[str],
        idx: int,
        uci: str,
        white_clock_time: int,
        black_clock_time: int,
        *,
        exclude: str | None = None,
    ) -> None:
        recipients = [u for u in usernames if u != exclude]
        self.moves.append((recipients, idx, uci, white_clock_time, black_clock_time))

    async def publish_game_end(
        self,
        usernames: list[str],
        status: str,
        rating_changes: dict[str, float],
    ) -> None:
        self.game_ends.append((list(usernames), status, rating_changes))


def ranking_params() -> RankingParams:
    return RankingParams(
        mu=25.0,
        sigma=8.333,
        beta=4.166,
        tau=0.083,
        epsilon=0.0,
    )


def seats() -> tuple[Seat, Seat, Seat, Seat]:
    return tuple(Seat(username=name, rating=25.0) for name in PLAYER_NAMES)  # type: ignore[return-value]


class GameObjTests(unittest.TestCase):
    def test_player_helpers_match_bughouse_seat_layout(self) -> None:
        game = GameObj(
            id=uuid4(),
            players=tuple(
                PlayerRef(username=name, rating_before=25.0, sigma_before=8.333)
                for name in PLAYER_NAMES
            ),  # type: ignore[arg-type]
            boards=BughouseBoards(),
            clocks=SimpleNamespace(),
            config=LobbyConfig(),
        )

        self.assertEqual(game.usernames, list(PLAYER_NAMES))
        self.assertEqual(game.board_of("alice"), 0)
        self.assertEqual(game.board_of("carol"), 1)
        self.assertEqual(game.color_of("alice"), chess.WHITE)
        self.assertEqual(game.color_of("bob"), chess.BLACK)
        self.assertEqual(game.partner_of("alice"), "dave")
        self.assertEqual(game.partner_of("bob"), "carol")
        self.assertTrue(game.is_turn_of("alice"))
        self.assertFalse(game.is_turn_of("bob"))


class BughouseBoardsTests(unittest.TestCase):
    def test_capture_transfers_piece_to_partner_pocket(self) -> None:
        boards = BughouseBoards()

        boards.push(0, "e2e4")
        boards.push(0, "d7d5")
        result = boards.push(0, "e4d5")

        self.assertEqual(result.captured, chess.PAWN)
        self.assertEqual(boards.last_move(0), "e4d5")
        self.assertEqual(boards.board_pockets(0), {"w": {}, "b": {}})
        self.assertEqual(boards.board_pockets(1), {"w": {}, "b": {"P": 1}})
        self.assertEqual(boards.to_snapshot(0)["last_move"], "e4d5")

    def test_illegal_move_is_rejected_without_changing_board(self) -> None:
        boards = BughouseBoards()
        before = boards.fen(0)

        with self.assertRaises(chess.IllegalMoveError):
            boards.push(0, "e2e5")

        self.assertEqual(boards.fen(0), before)
        self.assertIsNone(boards.last_move(0))


class GameManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.users = {name: make_user(name) for name in PLAYER_NAMES}
        self.session_factory = FakeSessionFactory(self.users)
        self.notifier = FakeNotifier()
        self.manager = GameManager(
            notifier=self.notifier,  # type: ignore[arg-type]
            session_factory=self.session_factory,  # type: ignore[arg-type]
            ranking=ranking_params(),
            abort_timeout=999_000.0,
        )
        self._patches = (
            patch.object(game_manager_module, "UserRepository", FakeUserRepository),
            patch.object(game_manager_module, "GameRepository", FakeGameRepository),
        )
        for patcher in self._patches:
            patcher.start()

    async def asyncTearDown(self) -> None:
        for patcher in reversed(self._patches):
            patcher.stop()

        abort_tasks = list(self.manager._abort_tasks.values())
        for task in abort_tasks:
            task.cancel()
        if abort_tasks:
            await asyncio.gather(*abort_tasks, return_exceptions=True)

        for game in list(self.manager._games.values()):
            await game.clocks.shutdown()

    async def create_game(
        self,
        *,
        config: LobbyConfig | None = None,
        abort_timeout: float | None = None,
    ) -> object:
        if abort_timeout is not None:
            self.manager._abort_timeout = abort_timeout
        return await self.manager.create_game(
            seats(),
            config or LobbyConfig(clock_time=60_000, incr=1_000, rated=False),
        )

    async def test_create_game_loads_players_and_publishes_initial_state(self) -> None:
        game_id = await self.create_game()

        game = self.manager._games[game_id]
        self.assertEqual([p.username for p in game.players], list(PLAYER_NAMES))
        self.assertEqual(self.notifier.busy, list(PLAYER_NAMES))
        self.assertEqual(len(self.notifier.game_starts), 1)
        usernames, bughouse = self.notifier.game_starts[0]
        self.assertEqual(usernames, list(PLAYER_NAMES))
        self.assertEqual(bughouse.boards[0].players[0].name, "alice")
        self.assertEqual(bughouse.boards[1].players[1].name, "dave")
        self.assertEqual(bughouse.incr, 1_000)
        self.assertIs(self.manager.get_game_by_user("carol"), game)

    async def test_make_move_records_move_publishes_to_other_players_and_advances_turn(self) -> None:
        game_id = await self.create_game()

        await self.manager.make_move("alice", "e2e4")

        game = self.manager._games[game_id]
        self.assertEqual(len(game.moves), 1)
        record = game.moves[0]
        self.assertEqual(record.board, 0)
        self.assertEqual(record.username, "alice")
        self.assertEqual(record.uci, "e2e4")
        self.assertEqual(record.index, 0)
        self.assertFalse(game.is_turn_of("alice"))
        self.assertTrue(game.is_turn_of("bob"))
        self.assertNotIn(game_id, self.manager._abort_tasks)
        self.assertEqual(len(self.notifier.moves), 1)
        usernames, board_idx, uci, white_clock_time, black_clock_time = self.notifier.moves[0]
        self.assertEqual(usernames, ["bob", "carol", "dave"])
        self.assertEqual((board_idx, uci), (0, "e2e4"))
        self.assertEqual(white_clock_time, 60_000)
        self.assertEqual(black_clock_time, 60_000)
        self.assertEqual(game.clocks._active, {})

    async def test_clock_starts_after_both_players_made_first_board_moves(self) -> None:
        game_id = await self.create_game()
        game = self.manager._games[game_id]

        await asyncio.sleep(0.02)
        self.assertEqual(game.clocks.snapshot()["b0w"], 60_000)
        self.assertEqual(game.clocks._active, {})

        await self.manager.make_move("alice", "e2e4")
        await asyncio.sleep(0.02)
        self.assertEqual(game.clocks.snapshot()["b0w"], 60_000)
        self.assertEqual(game.clocks.snapshot()["b0b"], 60_000)
        self.assertEqual(game.clocks._active, {})

        await self.manager.make_move("bob", "e7e5")

        active = game.clocks._active.get(0)
        self.assertIsNotNone(active)
        assert active is not None
        self.assertEqual(active[0], chess.WHITE)

        await asyncio.sleep(0.02)
        snap = game.clocks.snapshot()
        self.assertLess(snap["b0w"], 60_000)
        self.assertEqual(snap["b0b"], 60_000)
        self.assertEqual(snap["b1w"], 60_000)

    async def test_make_move_rejects_out_of_turn_and_illegal_moves(self) -> None:
        await self.create_game()

        with self.assertRaises(GameError) as turn_error:
            await self.manager.make_move("bob", "e7e5")
        self.assertEqual(turn_error.exception.code, ERR_NOT_YOUR_TURN)

        with self.assertRaises(GameError) as move_error:
            await self.manager.make_move("alice", "e2e5")
        self.assertEqual(move_error.exception.code, ERR_ILLEGAL_MOVE)
        self.assertEqual(self.notifier.moves, [])

    async def test_checkmate_finishes_game_persists_moves_and_cleans_users(self) -> None:
        game_id = await self.create_game()

        await self.manager.make_move("alice", "f2f3")
        await self.manager.make_move("bob", "e7e5")
        await self.manager.make_move("alice", "g2g4")
        await self.manager.make_move("bob", "d8h4")

        self.assertNotIn(game_id, self.manager._games)
        self.assertIsNone(self.manager.get_game_by_user("alice"))
        self.assertEqual(self.notifier.idle, list(PLAYER_NAMES))
        self.assertEqual(len(self.notifier.game_ends), 1)
        usernames, status, rating_changes = self.notifier.game_ends[0]
        self.assertEqual(usernames, list(PLAYER_NAMES))
        self.assertEqual(status, "WinB")
        self.assertEqual(rating_changes, {name: 0.0 for name in PLAYER_NAMES})

        self.assertEqual(len(self.session_factory.created_games), 1)
        persisted = self.session_factory.created_games[0]
        self.assertEqual(persisted["result"], GameResult.TEAM_B.value)
        self.assertEqual(
            [move[0] for move in persisted["moves"]],
            ["f2f3", "e7e5", "g2g4", "d8h4"],
        )

    async def test_resign_finishes_for_opposing_team(self) -> None:
        await self.create_game()

        await self.manager.resign("dave")

        self.assertEqual(len(self.notifier.game_ends), 1)
        _usernames, status, _rating_changes = self.notifier.game_ends[0]
        self.assertEqual(status, "WinB")
        self.assertEqual(self.session_factory.created_games[0]["result"], GameResult.TEAM_B.value)

    async def test_handle_flag_finishes_for_flagged_players_opponent_team(self) -> None:
        game_id = await self.create_game()

        await self.manager.handle_flag(game_id, 1, chess.BLACK)

        self.assertNotIn(game_id, self.manager._games)
        self.assertEqual(self.notifier.game_ends[0][1], "WinB")
        self.assertEqual(self.session_factory.created_games[0]["result"], GameResult.TEAM_B.value)

    async def test_abort_watchdog_finishes_game_without_moves(self) -> None:
        self.manager._abort_timeout = 10.0
        game_id = await self.create_game()

        await asyncio.sleep(0.05)

        self.assertNotIn(game_id, self.manager._games)
        self.assertEqual(self.notifier.game_ends[0][1], "Abort")
        self.assertEqual(self.session_factory.created_games[0]["result"], GameResult.ABORT.value)

    async def test_abort_watchdog_does_not_leave_finished_game_in_snapshot(self) -> None:
        sessions = UserSessionIndex(
            lobbies=SimpleNamespace(get_by_user=lambda _username: None),  # type: ignore[arg-type]
            games=self.manager,
        )
        self.manager._abort_timeout = 10.0
        await self.create_game()

        await asyncio.sleep(0.05)

        sync = sessions.get_sync("alice")
        self.assertEqual(sync.state, "IDLE")
        self.assertIsNone(sync.game)

    async def test_create_game_rejects_missing_user(self) -> None:
        self.users.pop("carol")

        with self.assertRaises(GameError) as error:
            await self.create_game()

        self.assertEqual(error.exception.code, "user_not_found")
        self.assertEqual(self.notifier.busy, [])


class GameManagerPrivateMappingTests(unittest.TestCase):
    def test_loser_team_mapping_matches_documented_team_layout(self) -> None:
        self.assertEqual(game_manager_module._loser_team_from_pos(0), GameResult.TEAM_A)
        self.assertEqual(game_manager_module._loser_team_from_pos(3), GameResult.TEAM_A)
        self.assertEqual(game_manager_module._loser_team_from_pos(1), GameResult.TEAM_B)
        self.assertEqual(game_manager_module._loser_team_from_pos(2), GameResult.TEAM_B)

    def test_position_to_board_and_color_mapping(self) -> None:
        self.assertEqual(game_manager_module._pos_to_board(0), 0)
        self.assertEqual(game_manager_module._pos_to_board(1), 0)
        self.assertEqual(game_manager_module._pos_to_board(2), 1)
        self.assertEqual(game_manager_module._pos_to_board(3), 1)
        self.assertEqual(game_manager_module._pos_to_color(0), chess.WHITE)
        self.assertEqual(game_manager_module._pos_to_color(1), chess.BLACK)
        self.assertEqual(game_manager_module._pos_to_color(2), chess.WHITE)
        self.assertEqual(game_manager_module._pos_to_color(3), chess.BLACK)


if __name__ == "__main__":
    unittest.main()
