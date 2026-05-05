from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

import chess

import services.core.game.manager as game_manager_module
import services.core.game.models as game_models_module
from services.core.game.board import BughouseBoards
from services.core.game.errors import (
    ERR_ILLEGAL_MOVE,
    ERR_NOT_YOUR_TURN,
    GameError,
)
from services.core.game.manager import GameManager
from services.core.game.models import (
    EndReason,
    GameObj,
    GameResult,
    PlayerRef,
    pos_for,
    pos_to_board,
    pos_to_color,
    team_of_pos,
)
from services.core.lobby.models import Lobby, LobbyConfig, LobbyState, Seat
from services.core.session import UserSessionIndex
from shared.events import BughouseData, GameChatData
from shared.infrastructure import RankingParams


# Position semantics (frontend layout):
#   0 — leader, 1 — partner, 2 — leader's same-board opp, 3 — partner's same-board opp.
#   Team A = (0, 1); Team B = (2, 3).
#   Boards: pos % 2 (0,2 → board 0; 1,3 → board 1).
#   Color: chosen at match time via `color_flip`. Without flip: pos 0,3 white, 1,2 black.
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
        self.moves: list[tuple[list[str], int, str, int, int, int | None]] = []
        self.chats: list[tuple[str, GameChatData]] = []
        self.game_ends: list[tuple[list[str], str, dict[str, float]]] = []
        self.back_to_lobby: list[tuple[str, object]] = []
        self.back_to_idle: list[str] = []

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
        auto_abort_at: int | None,
        *,
        exclude: str | None = None,
    ) -> None:
        recipients = [u for u in usernames if u != exclude]
        self.moves.append(
            (recipients, idx, uci, white_clock_time, black_clock_time, auto_abort_at)
        )

    async def publish_game_chat(self, username: str, message: GameChatData) -> None:
        self.chats.append((username, message))

    async def publish_game_end(
        self,
        usernames: list[str],
        status: str,
        rating_changes: dict[str, float],
    ) -> None:
        self.game_ends.append((list(usernames), status, rating_changes))

    async def publish_back_to_lobby(self, username: str, lobby: object) -> None:
        self.back_to_lobby.append((username, lobby))

    async def publish_back_to_idle(self, username: str) -> None:
        self.back_to_idle.append(username)


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

        # alice=0 (leader, board0 white), bob=1 (partner, board1 black),
        # carol=2 (leader's opp, board0 black), dave=3 (partner's opp, board1 white).
        self.assertEqual(game.usernames, list(PLAYER_NAMES))
        self.assertEqual(game.board_of("alice"), 0)
        self.assertEqual(game.board_of("bob"), 1)
        self.assertEqual(game.board_of("carol"), 0)
        self.assertEqual(game.board_of("dave"), 1)
        self.assertEqual(game.color_of("alice"), chess.WHITE)
        self.assertEqual(game.color_of("bob"), chess.BLACK)
        self.assertEqual(game.color_of("carol"), chess.BLACK)
        self.assertEqual(game.color_of("dave"), chess.WHITE)
        self.assertEqual(game.partner_of("alice"), "bob")
        self.assertEqual(game.partner_of("bob"), "alice")
        self.assertEqual(game.partner_of("carol"), "dave")
        self.assertEqual(game.partner_of("dave"), "carol")
        # Both boards start with white-to-move: alice (board 0 white) and dave (board 1 white).
        self.assertTrue(game.is_turn_of("alice"))
        self.assertFalse(game.is_turn_of("bob"))
        self.assertFalse(game.is_turn_of("carol"))
        self.assertTrue(game.is_turn_of("dave"))


class GameObjColorFlipTests(unittest.TestCase):
    def test_color_flip_swaps_colors_per_position(self) -> None:
        game = GameObj(
            id=uuid4(),
            players=tuple(
                PlayerRef(username=name, rating_before=25.0, sigma_before=8.333)
                for name in PLAYER_NAMES
            ),  # type: ignore[arg-type]
            boards=BughouseBoards(),
            clocks=SimpleNamespace(),
            config=LobbyConfig(),
            color_flip=True,
        )

        self.assertEqual(game.color_of("alice"), chess.BLACK)
        self.assertEqual(game.color_of("bob"), chess.WHITE)
        self.assertEqual(game.color_of("carol"), chess.WHITE)
        self.assertEqual(game.color_of("dave"), chess.BLACK)
        # Boards are independent of color flip.
        self.assertEqual(game.board_of("alice"), 0)
        self.assertEqual(game.board_of("dave"), 1)


class BughouseBoardsTests(unittest.TestCase):
    def test_capture_transfers_piece_to_partner_fen_reserve(self) -> None:
        boards = BughouseBoards()

        boards.push(0, "e2e4")
        boards.push(0, "d7d5")
        result = boards.push(0, "e4d5")

        self.assertEqual(result.captured, chess.PAWN)
        self.assertEqual(boards.last_move(0), "e4d5")
        self.assertIn("[]", boards.fen(0))
        self.assertIn("[p]", boards.fen(1))
        self.assertEqual(boards.to_snapshot(0)["last_move"], "e4d5")
        self.assertNotIn("pockets", boards.to_snapshot(0))

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
        color_flip: bool = False,
        lobby_ids: tuple[UUID | None, UUID | None, UUID | None, UUID | None] = (
            None, None, None, None,
        ),
    ) -> UUID:
        if abort_timeout is not None:
            self.manager._abort_timeout = abort_timeout
        return await self.manager.create_game(
            seats(),
            config or LobbyConfig(clock_time=60_000, incr=1_000, rated=False),
            color_flip=color_flip,
            lobby_ids=lobby_ids,
        )

    async def test_create_game_loads_players_and_publishes_initial_state(self) -> None:
        game_id = await self.create_game()

        game = self.manager._games[game_id]
        self.assertEqual([p.username for p in game.players], list(PLAYER_NAMES))
        self.assertEqual(self.notifier.busy, list(PLAYER_NAMES))
        self.assertEqual(len(self.notifier.game_starts), 1)
        usernames, bughouse = self.notifier.game_starts[0]
        self.assertEqual(usernames, list(PLAYER_NAMES))
        # Without color_flip: board 0 white = pos 0 (alice), black = pos 2 (carol).
        # board 1 white = pos 3 (dave), black = pos 1 (bob).
        self.assertEqual(bughouse.boards[0].players[0].name, "alice")
        self.assertEqual(bughouse.boards[0].players[1].name, "carol")
        self.assertEqual(bughouse.boards[1].players[0].name, "dave")
        self.assertEqual(bughouse.boards[1].players[1].name, "bob")
        self.assertEqual(bughouse.incr, 1_000)
        self.assertEqual(bughouse.auto_abort_timeout, 999_000)
        self.assertIsNotNone(bughouse.boards[0].auto_abort_at)
        self.assertIsNotNone(bughouse.boards[1].auto_abort_at)
        self.assertEqual(bughouse.chat, [])
        self.assertNotIn('"pocket"', bughouse.model_dump_json(by_alias=True))
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
        # On board 0 it is now black's turn — that is carol (pos 2), not bob.
        self.assertTrue(game.is_turn_of("carol"))
        self.assertFalse(game.is_turn_of("bob"))
        self.assertIn((game_id, 0), self.manager._abort_tasks)
        self.assertIn((game_id, 1), self.manager._abort_tasks)
        self.assertEqual(len(self.notifier.moves), 1)
        (
            usernames,
            board_idx,
            uci,
            white_clock_time,
            black_clock_time,
            auto_abort_at,
        ) = self.notifier.moves[0]
        self.assertEqual(usernames, ["bob", "carol", "dave"])
        self.assertEqual((board_idx, uci), (0, "e2e4"))
        self.assertEqual(white_clock_time, 60_000)
        self.assertEqual(black_clock_time, 60_000)
        self.assertEqual(auto_abort_at, game.auto_abort_at[0])
        self.assertIsNotNone(auto_abort_at)
        self.assertEqual(game.clocks._active, {})

    async def test_clock_starts_after_both_players_made_first_board_moves(self) -> None:
        game_id = await self.create_game()
        game = self.manager._games[game_id]

        await asyncio.sleep(0.02)
        self.assertEqual(game.clocks.snapshot()["b0w"], 60_000)
        self.assertEqual(game.clocks._active, {})

        # Board 0: alice (white pos 0) and carol (black pos 2) play here.
        await self.manager.make_move("alice", "e2e4")
        await asyncio.sleep(0.02)
        self.assertEqual(game.clocks.snapshot()["b0w"], 60_000)
        self.assertEqual(game.clocks.snapshot()["b0b"], 60_000)
        self.assertEqual(game.clocks._active, {})

        await self.manager.make_move("carol", "e7e5")

        active = game.clocks._active.get(0)
        self.assertIsNotNone(active)
        assert active is not None
        self.assertEqual(active[0], chess.WHITE)
        self.assertIsNone(game.auto_abort_at[0])
        self.assertIsNotNone(game.auto_abort_at[1])

        await asyncio.sleep(0.02)
        snap = game.clocks.snapshot()
        self.assertLess(snap["b0w"], 60_000)
        self.assertEqual(snap["b0b"], 60_000)
        self.assertEqual(snap["b1w"], 60_000)

    async def test_make_move_rejects_out_of_turn_and_illegal_moves(self) -> None:
        await self.create_game()

        # bob is on board 1 (black). Trying to move at game start (white-to-move on his board).
        with self.assertRaises(GameError) as turn_error:
            await self.manager.make_move("bob", "e7e5")
        self.assertEqual(turn_error.exception.code, ERR_NOT_YOUR_TURN)

        with self.assertRaises(GameError) as move_error:
            await self.manager.make_move("alice", "e2e5")
        self.assertEqual(move_error.exception.code, ERR_ILLEGAL_MOVE)
        self.assertEqual(self.notifier.moves, [])

    async def test_chat_goes_only_to_teammate_and_sync_history_is_private(self) -> None:
        await self.create_game()

        await self.manager.send_chat("alice", " hold knight ")

        self.assertEqual(len(self.notifier.chats), 1)
        recipient, message = self.notifier.chats[0]
        self.assertEqual(recipient, "bob")
        self.assertEqual(message.idx, 0)
        self.assertEqual(message.username, "alice")
        self.assertEqual(message.text, "hold knight")
        self.assertGreater(message.created_at, 0)

        sessions = UserSessionIndex(
            lobbies=SimpleNamespace(get_by_user=lambda _username: None),  # type: ignore[arg-type]
            games=self.manager,
        )
        alice_sync = sessions.get_sync("alice")
        bob_sync = sessions.get_sync("bob")
        carol_sync = sessions.get_sync("carol")
        self.assertIsNotNone(alice_sync.game)
        self.assertIsNotNone(bob_sync.game)
        self.assertIsNotNone(carol_sync.game)
        assert alice_sync.game is not None
        assert bob_sync.game is not None
        assert carol_sync.game is not None
        self.assertEqual(alice_sync.game.chat, [message])
        self.assertEqual(bob_sync.game.chat, [message])
        self.assertEqual(carol_sync.game.chat, [])

    async def test_auto_abort_deadline_is_available_in_sync_during_first_moves(self) -> None:
        game_id = await self.create_game()
        game = self.manager._games[game_id]

        await self.manager.make_move("alice", "e2e4")

        sessions = UserSessionIndex(
            lobbies=SimpleNamespace(get_by_user=lambda _username: None),  # type: ignore[arg-type]
            games=self.manager,
        )
        sync = sessions.get_sync("bob")
        self.assertIsNotNone(sync.game)
        assert sync.game is not None
        self.assertEqual(sync.game.boards[0].auto_abort_at, game.auto_abort_at[0])
        self.assertEqual(sync.game.boards[1].auto_abort_at, game.auto_abort_at[1])
        self.assertIsNotNone(sync.game.boards[0].auto_abort_at)
        self.assertIsNotNone(sync.game.boards[1].auto_abort_at)

        await self.manager.make_move("carol", "e7e5")

        sync_after_black = sessions.get_sync("bob")
        self.assertIsNotNone(sync_after_black.game)
        assert sync_after_black.game is not None
        self.assertIsNone(sync_after_black.game.boards[0].auto_abort_at)
        self.assertIsNotNone(sync_after_black.game.boards[1].auto_abort_at)

    async def test_checkmate_finishes_game_persists_moves_and_cleans_users(self) -> None:
        game_id = await self.create_game()

        # Fool's mate on board 0: alice (white pos 0) vs carol (black pos 2).
        await self.manager.make_move("alice", "f2f3")
        await self.manager.make_move("carol", "e7e5")
        await self.manager.make_move("alice", "g2g4")
        await self.manager.make_move("carol", "d8h4")

        self.assertNotIn(game_id, self.manager._games)
        self.assertIsNone(self.manager.get_game_by_user("alice"))
        # No lobby manager attached: backend marks online players idle,
        # but the finished game screen is not forced away by a sync push.
        self.assertEqual(self.notifier.idle, list(PLAYER_NAMES))
        self.assertEqual(self.notifier.back_to_idle, [])
        self.assertEqual(self.notifier.back_to_lobby, [])
        self.assertEqual(len(self.notifier.game_ends), 1)
        usernames, status, rating_changes = self.notifier.game_ends[0]
        self.assertEqual(usernames, list(PLAYER_NAMES))
        # Carol (pos 2 → team B) checkmated alice (pos 0 → team A). Team B wins.
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

        # dave is at pos 3 → team B. Resigning means team B loses → team A wins (WinA).
        await self.manager.resign("dave")

        self.assertEqual(len(self.notifier.game_ends), 1)
        _usernames, status, _rating_changes = self.notifier.game_ends[0]
        self.assertEqual(status, "WinA")
        self.assertEqual(self.session_factory.created_games[0]["result"], GameResult.TEAM_A.value)

    async def test_handle_flag_finishes_for_flagged_players_opponent_team(self) -> None:
        game_id = await self.create_game()

        # board 1 black without color_flip → pos 1 (bob, team A). Team A flagged → WinB.
        await self.manager.handle_flag(game_id, 1, chess.BLACK)

        self.assertNotIn(game_id, self.manager._games)
        self.assertEqual(self.notifier.game_ends[0][1], "WinB")
        self.assertEqual(self.session_factory.created_games[0]["result"], GameResult.TEAM_B.value)

    async def test_handle_flag_with_color_flip_inverts_color_to_pos_mapping(self) -> None:
        game_id = await self.create_game(color_flip=True)

        # With color_flip=True: board 1 black → pos 3 (dave, team B). Team B flagged → WinA.
        await self.manager.handle_flag(game_id, 1, chess.BLACK)

        self.assertEqual(self.notifier.game_ends[0][1], "WinA")
        self.assertEqual(self.session_factory.created_games[0]["result"], GameResult.TEAM_A.value)

    async def test_abort_watchdog_finishes_game_without_moves(self) -> None:
        self.manager._abort_timeout = 10.0
        game_id = await self.create_game()

        await asyncio.sleep(0.05)

        self.assertNotIn(game_id, self.manager._games)
        self.assertEqual(self.notifier.game_ends[0][1], "Abort")
        self.assertEqual(self.session_factory.created_games[0]["result"], GameResult.ABORT.value)

    async def test_abort_watchdog_finishes_if_black_does_not_reply(self) -> None:
        self.manager._abort_timeout = 20.0
        game_id = await self.create_game()

        await self.manager.make_move("alice", "e2e4")
        await self.manager.make_move("dave", "d2d4")
        await asyncio.sleep(0.06)

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

    async def test_finish_releases_lobbies_without_forcing_client_sync(self) -> None:
        # Stub a minimal lobby manager: maps usernames to lobby ids.
        lobby_a, lobby_b = uuid4(), uuid4()
        per_user_lobby = {
            "alice": lobby_a,
            "bob": lobby_a,
            "carol": lobby_b,
            "dave": lobby_b,
        }
        released: list[UUID] = []
        sentinel_lobbies = {
            lobby_a: Lobby(
                id=lobby_a,
                leader="alice",
                seats=[
                    Seat(username="alice", rating=25.0),
                    Seat(username="bob", rating=25.0),
                    None,
                    None,
                ],
                config=LobbyConfig(),
                state=LobbyState.IN_GAME,
            ),
            lobby_b: Lobby(
                id=lobby_b,
                leader="carol",
                seats=[
                    Seat(username="carol", rating=25.0),
                    Seat(username="dave", rating=25.0),
                    None,
                    None,
                ],
                config=LobbyConfig(),
                state=LobbyState.IN_GAME,
            ),
        }

        class StubLobbyMgr:
            def get_by_user(self, username: str) -> Lobby | None:
                lobby_id = per_user_lobby.get(username)
                return sentinel_lobbies.get(lobby_id) if lobby_id else None

            async def release_from_game(self, lobby_id: UUID) -> Lobby | None:
                released.append(lobby_id)
                lobby = sentinel_lobbies.get(lobby_id)
                if lobby is not None:
                    lobby.state = LobbyState.IDLE
                return lobby

        stub_lobbies = StubLobbyMgr()
        self.manager.attach_lobby_manager(stub_lobbies)  # type: ignore[arg-type]

        await self.create_game(
            lobby_ids=(lobby_a, lobby_a, lobby_b, lobby_b),
        )
        await self.manager.resign("alice")

        # Each lobby is released exactly once.
        self.assertEqual(sorted(released), sorted([lobby_a, lobby_b]))
        self.assertEqual(sentinel_lobbies[lobby_a].state, LobbyState.IDLE)
        self.assertEqual(sentinel_lobbies[lobby_b].state, LobbyState.IDLE)
        # Clients receive GAME_END only; leaving the finished game screen is explicit.
        self.assertEqual(self.notifier.back_to_lobby, [])
        self.assertEqual(self.notifier.back_to_idle, [])
        # No idle marks because everyone is still in a lobby.
        self.assertEqual(self.notifier.idle, [])

        sessions = UserSessionIndex(
            lobbies=stub_lobbies,  # type: ignore[arg-type]
            games=self.manager,
        )
        sync = sessions.get_sync("alice")
        self.assertEqual(sync.state, "LOBBY")
        self.assertIsNotNone(sync.lobby)
        assert sync.lobby is not None
        self.assertFalse(sync.lobby.in_queue)
        self.assertIsNone(sync.game)


class PositionMappingTests(unittest.TestCase):
    def test_team_layout(self) -> None:
        self.assertEqual(team_of_pos(0), GameResult.TEAM_A)
        self.assertEqual(team_of_pos(1), GameResult.TEAM_A)
        self.assertEqual(team_of_pos(2), GameResult.TEAM_B)
        self.assertEqual(team_of_pos(3), GameResult.TEAM_B)

    def test_board_layout(self) -> None:
        self.assertEqual(pos_to_board(0), 0)
        self.assertEqual(pos_to_board(1), 1)
        self.assertEqual(pos_to_board(2), 0)
        self.assertEqual(pos_to_board(3), 1)

    def test_color_layout_no_flip(self) -> None:
        self.assertEqual(pos_to_color(0, False), chess.WHITE)
        self.assertEqual(pos_to_color(1, False), chess.BLACK)
        self.assertEqual(pos_to_color(2, False), chess.BLACK)
        self.assertEqual(pos_to_color(3, False), chess.WHITE)

    def test_color_layout_with_flip(self) -> None:
        self.assertEqual(pos_to_color(0, True), chess.BLACK)
        self.assertEqual(pos_to_color(1, True), chess.WHITE)
        self.assertEqual(pos_to_color(2, True), chess.WHITE)
        self.assertEqual(pos_to_color(3, True), chess.BLACK)

    def test_pos_for_round_trips_through_board_and_color(self) -> None:
        for flip in (False, True):
            for pos in (0, 1, 2, 3):
                board = pos_to_board(pos)
                color = pos_to_color(pos, flip)
                self.assertEqual(pos_for(board, color, flip), pos)


if __name__ == "__main__":
    unittest.main()
