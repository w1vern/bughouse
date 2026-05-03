from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol
from uuid import UUID, uuid4

import chess
import trueskill
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database import GameRepository, User, UserRepository
from shared.infrastructure import RankingParams, setup_logger

from ..lobby.models import Lobby, LobbyConfig, Seat
from ..notifier import Notifier, result_status
from .board import BughouseBoards
from .clocks import Clocks, FlagCallback
from .errors import GameError
from .models import (
    EndReason,
    GameObj,
    GameResult,
    MoveRecord,
    PlayerRef,
    other_team,
    pos_for,
    pos_to_board,
    pos_to_color,
    team_of_pos,
)
from .state import build_bughouse

logger = setup_logger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class _LobbyManagerProto(Protocol):
    def get_by_user(self, username: str) -> Lobby | None: ...
    async def release_from_game(self, lobby_id: UUID) -> Lobby | None: ...


def _board_move_count(game: GameObj, board_idx: int) -> int:
    return sum(1 for move in game.moves if move.board == board_idx)


class GameManager:
    def __init__(
        self,
        notifier: Notifier,
        session_factory: SessionFactory,
        ranking: RankingParams,
        abort_timeout: float,
        lobby_mgr: _LobbyManagerProto | None = None,
    ) -> None:
        self._games: dict[UUID, GameObj] = {}
        self._user_to_game: dict[str, UUID] = {}
        self._notifier = notifier
        self._session_factory = session_factory
        self._ranking = ranking
        self._abort_timeout = abort_timeout
        self._abort_tasks: dict[UUID, asyncio.Task[None]] = {}
        self._lobby_mgr: _LobbyManagerProto | None = lobby_mgr
        self._ts = trueskill.TrueSkill(
            mu=ranking.mu,
            sigma=ranking.sigma,
            beta=ranking.beta,
            tau=ranking.tau,
            draw_probability=0.0,
        )

    def attach_lobby_manager(self, lobby_mgr: _LobbyManagerProto) -> None:
        self._lobby_mgr = lobby_mgr

    def get_game_by_user(self, username: str) -> GameObj | None:
        game_id = self._user_to_game.get(username)
        if game_id is None:
            return None
        return self._games.get(game_id)

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
        async with self._session_factory() as session:
            user_repo = UserRepository(session)
            players_list: list[PlayerRef] = []
            for seat, lobby_id in zip(seats, lobby_ids):
                user = await user_repo.get_by_username(seat.username)
                if user is None:
                    raise GameError("user_not_found", f"user {seat.username}")
                players_list.append(
                    PlayerRef(
                        username=user.username,
                        rating_before=user.rating,
                        sigma_before=user.sigma,
                        lobby_id=lobby_id,
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
            clocks=Clocks(config.clock_time),
            config=config,
            color_flip=color_flip,
            started_at=time.monotonic(),
        )
        self._games[game.id] = game
        for p in players:
            self._user_to_game[p.username] = game.id
            await self._notifier.mark_busy(p.username)

        await self._notifier.publish_game_start(game.usernames, build_bughouse(game))

        self._abort_tasks[game.id] = asyncio.create_task(
            self._abort_watchdog(game.id)
        )

        return game.id

    async def make_move(
        self,
        username: str,
        uci: str,
    ) -> None:
        game = self.get_game_by_user(username)
        if game is None:
            raise GameError.not_found()
        if game.finished:
            raise GameError.already_finished()
        try:
            pos = game.pos_of(username)
        except KeyError as exc:
            raise GameError.not_in_this_game() from exc
        board_idx = pos_to_board(pos)
        expected_color = pos_to_color(pos, game.color_flip)
        if game.boards.turn(board_idx) != expected_color:
            raise GameError.not_your_turn()

        board_moves_before = _board_move_count(game, board_idx)

        try:
            game.boards.push(board_idx, uci)
        except (chess.IllegalMoveError, chess.InvalidMoveError, ValueError) as exc:
            raise GameError.illegal_move(str(exc)) from exc

        spent = 0
        if board_moves_before >= 2:
            spent = await game.clocks.stop_and_apply(board_idx, game.config.incr)
        game.moves.append(
            MoveRecord(
                board=board_idx,
                username=username,
                uci=uci,
                spent=spent,
                index=len(game.moves),
            )
        )

        abort = self._abort_tasks.pop(game.id, None)
        if abort is not None:
            abort.cancel()

        if game.boards.is_checkmate(board_idx):
            loser_color = game.boards.turn(board_idx)
            loser_pos = pos_for(board_idx, loser_color, game.color_flip)
            loser_team = team_of_pos(loser_pos)
            winner = other_team(loser_team)
            await self._publish_move(game, board_idx, uci, exclude=username)
            await self._finish(game, winner, EndReason.CHECKMATE)
            return

        if game.boards.is_draw_rule():
            await self._publish_move(game, board_idx, uci, exclude=username)
            await self._finish(game, GameResult.DRAW, EndReason.DRAW_RULE)
            return

        next_color = game.boards.turn(board_idx)
        if board_moves_before >= 1:
            await game.clocks.start(board_idx, next_color, self._make_flag_cb(game.id))

        await self._publish_move(game, board_idx, uci, exclude=username)

    async def resign(self, username: str) -> None:
        game = self.get_game_by_user(username)
        if game is None:
            raise GameError.not_found()
        if game.finished:
            raise GameError.already_finished()
        try:
            pos = game.pos_of(username)
        except KeyError as exc:
            raise GameError.not_in_this_game() from exc
        loser_team = team_of_pos(pos)
        winner = other_team(loser_team)
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
        flagged_pos = pos_for(board_idx, color, game.color_flip)
        loser_team = team_of_pos(flagged_pos)
        winner = other_team(loser_team)
        await self._finish(game, winner, EndReason.TIMEOUT)

    # ---------------- Internals ----------------

    async def _publish_move(
        self,
        game: GameObj,
        board_idx: int,
        uci: str,
        *,
        exclude: str | None = None,
    ) -> None:
        snap = game.clocks.snapshot()
        if board_idx == 0:
            white_clock_time, black_clock_time = snap["b0w"], snap["b0b"]
        else:
            white_clock_time, black_clock_time = snap["b1w"], snap["b1b"]
        await self._notifier.publish_move(
            game.usernames,
            board_idx,
            uci,
            white_clock_time,
            black_clock_time,
            exclude=exclude,
        )

    def _make_flag_cb(self, game_id: UUID) -> FlagCallback:
        async def cb(board_idx: int, color: chess.Color) -> None:
            await self.handle_flag(game_id, board_idx, color)

        return cb

    async def _abort_watchdog(self, game_id: UUID) -> None:
        try:
            await asyncio.sleep(self._abort_timeout / 1000)
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
            self._detach_game(game)
            return
        game.finished = True
        game.result = result
        game.reason = reason
        game.ended_at = time.monotonic()

        self._detach_game(game)

        abort = self._abort_tasks.pop(game.id, None)
        if abort is not None and abort is not asyncio.current_task():
            abort.cancel()

        try:
            await game.clocks.shutdown()

            diffs = (0.0, 0.0, 0.0, 0.0)
            try:
                diffs = await self._persist(game, result)
            except Exception:
                logger.exception("failed to persist game %s", game.id)

            rating_changes = {
                game.players[i].username: diffs[i] for i in range(4)
            }
            await self._notifier.publish_game_end(
                game.usernames, result_status(result), rating_changes
            )

            await self._return_to_lobbies(game)
        finally:
            self._detach_game(game)

    async def _return_to_lobbies(self, game: GameObj) -> None:
        """Send each player back to their pre-game lobby (if any), or mark idle."""
        lobby_mgr = self._lobby_mgr
        released: dict[UUID, Lobby | None] = {}
        for p in game.players:
            lobby_id = p.lobby_id
            if lobby_mgr is None or lobby_id is None:
                await self._notifier.mark_idle_if_online(p.username)
                await self._notifier.publish_back_to_idle(p.username)
                continue
            if lobby_id not in released:
                released[lobby_id] = await lobby_mgr.release_from_game(lobby_id)
            lobby = released[lobby_id]
            if lobby is None:
                await self._notifier.mark_idle_if_online(p.username)
                await self._notifier.publish_back_to_idle(p.username)
                continue
            await self._notifier.publish_back_to_lobby(p.username, lobby)

    def _detach_game(self, game: GameObj) -> None:
        self._games.pop(game.id, None)
        for p in game.players:
            if self._user_to_game.get(p.username) == game.id:
                self._user_to_game.pop(p.username, None)

    async def _persist(
        self,
        game: GameObj,
        result: GameResult,
    ) -> tuple[float, float, float, float]:
        async with self._session_factory() as session:
            user_repo = UserRepository(session)
            game_repo = GameRepository(session)

            users: list[User] = []
            for p in game.players:
                u = await user_repo.get_by_username(p.username)
                if u is None:
                    raise GameError("user_not_found", f"user {p.username}")
                users.append(u)

            for pos, user in enumerate(users):
                user.color += 1 if pos_to_color(pos, game.color_flip) == chess.WHITE else -1

            diffs: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
            if game.config.rated and result != GameResult.ABORT:
                old_mus = [u.rating for u in users]
                # Team A = positions (0, 1); Team B = positions (2, 3).
                team_a = (
                    self._ts.create_rating(users[0].rating, users[0].sigma),
                    self._ts.create_rating(users[1].rating, users[1].sigma),
                )
                team_b = (
                    self._ts.create_rating(users[2].rating, users[2].sigma),
                    self._ts.create_rating(users[3].rating, users[3].sigma),
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
                users[1].rating = new_a[1].mu
                users[1].sigma = new_a[1].sigma
                users[2].rating = new_b[0].mu
                users[2].sigma = new_b[0].sigma
                users[3].rating = new_b[1].mu
                users[3].sigma = new_b[1].sigma
                diffs = (
                    users[0].rating - old_mus[0],
                    users[1].rating - old_mus[1],
                    users[2].rating - old_mus[2],
                    users[3].rating - old_mus[3],
                )

            moves_payload: list[tuple[str, float, int, UUID]] = [
                (m.uci, m.spent / 1000.0, m.board, users[game.pos_of(m.username)].id)
                for m in game.moves
            ]

            await game_repo.create(
                result=result.value,
                game_time=game.config.clock_time / 1000.0,
                increment=game.config.incr / 1000.0,
                users=(users[0], users[1], users[2], users[3]),
                diffs=diffs,
                moves=moves_payload,
            )

            await session.commit()
            return diffs
