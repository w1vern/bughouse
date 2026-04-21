from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any
from uuid import UUID, uuid4

import chess
import trueskill
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database.repositories.game import GameRepository
from shared.database.repositories.user import UserRepository
from shared.infrastructure import setup_logger
from shared.infrastructure.config import RankingParams

from ..lobby.models import LobbyConfig, Seat
from ..notifier import Notifier
from .board import BughouseBoards
from .clocks import Clocks, FlagCallback
from .errors import GameError
from .models import EndReason, GameObj, GameResult, MoveRecord, PlayerRef

logger = setup_logger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def _pos_to_board(pos: int) -> int:
    return pos // 2


def _pos_to_color(pos: int) -> chess.Color:
    return chess.WHITE if pos % 2 == 0 else chess.BLACK


def _pos_of_player(game: GameObj, user_id: UUID) -> int:
    for i, p in enumerate(game.players):
        if p.user_id == user_id:
            return i
    raise GameError.not_in_this_game()


def _loser_team_from_pos(pos: int) -> GameResult:
    if pos in (1, 2):
        return GameResult.TEAM_A
    return GameResult.TEAM_B


class GameManager:
    def __init__(
        self,
        notifier: Notifier,
        session_factory: SessionFactory,
        ranking: RankingParams,
        abort_timeout_sec: float,
    ) -> None:
        self._games: dict[UUID, GameObj] = {}
        self._user_to_game: dict[UUID, UUID] = {}
        self._notifier = notifier
        self._session_factory = session_factory
        self._ranking = ranking
        self._abort_timeout_sec = abort_timeout_sec
        self._abort_tasks: dict[UUID, asyncio.Task[None]] = {}
        self._ts = trueskill.TrueSkill(
            mu=ranking.mu,
            sigma=ranking.sigma,
            beta=ranking.beta,
            tau=ranking.tau,
            draw_probability=0.0,
        )

    def get_game_by_user(self, user_id: UUID) -> GameObj | None:
        game_id = self._user_to_game.get(user_id)
        if game_id is None:
            return None
        return self._games.get(game_id)

    async def create_game(
        self,
        seats: tuple[Seat, Seat, Seat, Seat],
        config: LobbyConfig,
    ) -> UUID:
        async with self._session_factory() as session:
            user_repo = UserRepository(session)
            players_list: list[PlayerRef] = []
            for seat in seats:
                user = await user_repo.get_by_id(seat.user_id)
                if user is None:
                    raise GameError("user_not_found", f"user {seat.user_id}")
                players_list.append(
                    PlayerRef(
                        user_id=user.id,
                        username=user.username,
                        rating_before=user.rating,
                        sigma_before=user.sigma,
                    )
                )

        players: tuple[PlayerRef, PlayerRef, PlayerRef, PlayerRef] = (
            players_list[0],
            players_list[1],
            players_list[2],
            players_list[3],
        )

        game = GameObj(
            id=uuid4(),
            players=players,
            boards=BughouseBoards(),
            clocks=Clocks(config.initial_ms),
            config=config,
            started_at=time.monotonic(),
        )
        self._games[game.id] = game
        for p in players:
            self._user_to_game[p.user_id] = game.id

        flag_cb = self._make_flag_cb(game.id)
        await game.clocks.start(0, chess.WHITE, flag_cb)
        await game.clocks.start(1, chess.WHITE, flag_cb)

        await self._publish_start(game)

        self._abort_tasks[game.id] = asyncio.create_task(
            self._abort_watchdog(game.id)
        )

        return game.id

    async def make_move(
        self,
        game_id: UUID,
        user_id: UUID,
        uci: str,
    ) -> None:
        game = self._games.get(game_id)
        if game is None:
            raise GameError.not_found()
        if game.finished:
            raise GameError.already_finished()
        pos = _pos_of_player(game, user_id)
        board_idx = _pos_to_board(pos)
        expected_color = _pos_to_color(pos)
        if game.boards.turn(board_idx) != expected_color:
            raise GameError.not_your_turn()

        try:
            result = game.boards.push(board_idx, uci)
        except (chess.IllegalMoveError, chess.InvalidMoveError, ValueError) as exc:
            raise GameError.illegal_move(str(exc)) from exc

        ms_spent = await game.clocks.stop_and_apply(board_idx, game.config.increment_ms)
        game.moves.append(
            MoveRecord(
                board=board_idx,
                user_id=user_id,
                uci=uci,
                ms_spent=ms_spent,
                index=len(game.moves),
            )
        )

        abort = self._abort_tasks.pop(game.id, None)
        if abort is not None:
            abort.cancel()

        if game.boards.is_checkmate(board_idx):
            loser_color = game.boards.turn(board_idx)
            loser_pos = self._pos_for(board_idx, loser_color)
            loser_team = _loser_team_from_pos(loser_pos)
            winner = GameResult.TEAM_B if loser_team == GameResult.TEAM_A else GameResult.TEAM_A
            await self._finish(game, winner, EndReason.CHECKMATE)
            return

        if game.boards.is_draw_rule():
            await self._finish(game, GameResult.DRAW, EndReason.DRAW_RULE)
            return

        next_color = game.boards.turn(board_idx)
        await game.clocks.start(board_idx, next_color, self._make_flag_cb(game.id))

        next_pos = self._pos_for(board_idx, next_color)
        next_user_id = game.players[next_pos].user_id

        payload: dict[str, Any] = {
            "board": board_idx,
            "uci": uci,
            "fen_after": result.fen_after,
            "pockets_after": result.pockets_after,
            "clocks": game.clocks.snapshot(),
            "next_mover_id": str(next_user_id),
        }
        await self._notifier.publish_move(game, payload)

    async def resign(self, game_id: UUID, user_id: UUID) -> None:
        game = self._games.get(game_id)
        if game is None:
            raise GameError.not_found()
        if game.finished:
            raise GameError.already_finished()
        pos = _pos_of_player(game, user_id)
        loser_team = _loser_team_from_pos(pos)
        winner = GameResult.TEAM_B if loser_team == GameResult.TEAM_A else GameResult.TEAM_A
        await self._finish(game, winner, EndReason.RESIGN)

    async def handle_flag(
        self,
        game_id: UUID,
        board_idx: int,
        color: chess.Color,
    ) -> None:
        game = self._games.get(game_id)
        if game is None or game.finished:
            return
        flagged_pos = self._pos_for(board_idx, color)
        loser_team = _loser_team_from_pos(flagged_pos)
        winner = GameResult.TEAM_B if loser_team == GameResult.TEAM_A else GameResult.TEAM_A
        await self._finish(game, winner, EndReason.TIMEOUT)

    def get_snapshot(self, game_id: UUID, user_id: UUID) -> dict[str, Any]:
        game = self._games.get(game_id)
        if game is None:
            raise GameError.not_found()
        pos = _pos_of_player(game, user_id)
        board_idx = _pos_to_board(pos)
        color = _pos_to_color(pos)
        partner_pos = self._partner_pos(pos)
        opponents = [
            str(game.players[i].user_id) for i in range(4) if i != pos and i != partner_pos
        ]
        base = game.boards.to_snapshot(board_idx)
        base.update(
            {
                "game_id": str(game.id),
                "board": board_idx,
                "color": int(color),
                "partner_id": str(game.players[partner_pos].user_id),
                "opponents": opponents,
                "clocks": game.clocks.snapshot(),
                "your_turn": game.boards.turn(board_idx) == color,
            }
        )
        return base

    # ---------------- Internals ----------------

    def _make_flag_cb(self, game_id: UUID) -> FlagCallback:
        async def cb(board_idx: int, color: chess.Color) -> None:
            await self.handle_flag(game_id, board_idx, color)

        return cb

    def _pos_for(self, board_idx: int, color: chess.Color) -> int:
        color_idx = 0 if color == chess.WHITE else 1
        return board_idx * 2 + color_idx

    def _partner_pos(self, pos: int) -> int:
        # TEAM_A = {0, 3}; TEAM_B = {1, 2}
        partners = {0: 3, 3: 0, 1: 2, 2: 1}
        return partners[pos]

    async def _publish_start(self, game: GameObj) -> None:
        per_user: dict[str, dict[str, Any]] = {}
        for pos in range(4):
            board_idx = _pos_to_board(pos)
            color = _pos_to_color(pos)
            partner_pos = self._partner_pos(pos)
            opponents = [
                str(game.players[i].user_id)
                for i in range(4)
                if i != pos and i != partner_pos
            ]
            uid = str(game.players[pos].user_id)
            per_user[uid] = {
                "game_id": str(game.id),
                "board": board_idx,
                "color": int(color),
                "partner_id": str(game.players[partner_pos].user_id),
                "opponents": opponents,
                "initial_ms": game.config.initial_ms,
                "increment_ms": game.config.increment_ms,
            }
        await self._notifier.publish_game_start(game, per_user)

    async def _abort_watchdog(self, game_id: UUID) -> None:
        try:
            await asyncio.sleep(self._abort_timeout_sec)
        except asyncio.CancelledError:
            return
        game = self._games.get(game_id)
        if game is None or game.finished or game.moves:
            return
        try:
            await self._finish(game, GameResult.ABORT, EndReason.ABORT_NO_MOVES)
        except Exception:
            logger.exception("abort finish failed for game %s", game_id)

    async def _finish(
        self,
        game: GameObj,
        result: GameResult,
        reason: EndReason,
    ) -> None:
        if game.finished:
            return
        game.finished = True
        game.result = result
        game.reason = reason
        game.ended_at = time.monotonic()

        await game.clocks.shutdown()
        abort = self._abort_tasks.pop(game.id, None)
        if abort is not None:
            abort.cancel()

        for p in game.players:
            self._user_to_game.pop(p.user_id, None)

        diffs = (0.0, 0.0, 0.0, 0.0)
        try:
            diffs = await self._persist(game, result)
        except Exception:
            logger.exception("failed to persist game %s", game.id)

        payload: dict[str, Any] = {
            "result": result.name.lower(),
            "reason": reason.value,
            "rating_deltas": {
                str(game.players[i].user_id): diffs[i] for i in range(4)
            },
        }
        await self._notifier.publish_game_end(game, payload)

        self._games.pop(game.id, None)

    async def _persist(
        self,
        game: GameObj,
        result: GameResult,
    ) -> tuple[float, float, float, float]:
        async with self._session_factory() as session:
            user_repo = UserRepository(session)
            game_repo = GameRepository(session)

            users = []
            for p in game.players:
                u = await user_repo.get_by_id(p.user_id)
                if u is None:
                    raise GameError("user_not_found", f"user {p.user_id}")
                users.append(u)

            for pos, user in enumerate(users):
                user.color += 1 if _pos_to_color(pos) == chess.WHITE else -1

            diffs: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
            if game.config.rated and result != GameResult.ABORT:
                old_mus = [u.rating for u in users]
                team_a = (
                    self._ts.create_rating(users[0].rating, users[0].sigma),
                    self._ts.create_rating(users[3].rating, users[3].sigma),
                )
                team_b = (
                    self._ts.create_rating(users[1].rating, users[1].sigma),
                    self._ts.create_rating(users[2].rating, users[2].sigma),
                )
                if result == GameResult.TEAM_A:
                    ranks = [0, 1]
                elif result == GameResult.TEAM_B:
                    ranks = [1, 0]
                else:
                    ranks = [0, 0]
                new_a, new_b = self._ts.rate([team_a, team_b], ranks=ranks)
                users[0].rating = new_a[0].mu
                users[0].sigma = new_a[0].sigma
                users[3].rating = new_a[1].mu
                users[3].sigma = new_a[1].sigma
                users[1].rating = new_b[0].mu
                users[1].sigma = new_b[0].sigma
                users[2].rating = new_b[1].mu
                users[2].sigma = new_b[1].sigma
                diffs = (
                    users[0].rating - old_mus[0],
                    users[1].rating - old_mus[1],
                    users[2].rating - old_mus[2],
                    users[3].rating - old_mus[3],
                )

            moves_payload: list[tuple[str, float, int, UUID]] = [
                (m.uci, m.ms_spent / 1000.0, m.board, m.user_id) for m in game.moves
            ]

            await game_repo.create(
                result=result.value,
                game_time=game.config.initial_ms / 1000.0,
                increment=game.config.increment_ms / 1000.0,
                users=(users[0], users[1], users[2], users[3]),
                diffs=diffs,
                moves=moves_payload,
            )

            await session.commit()
            return diffs
