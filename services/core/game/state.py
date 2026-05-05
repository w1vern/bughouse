from __future__ import annotations

from dataclasses import dataclass

import chess

from shared.events import (
    BoardData,
    BughouseData,
    ClocksData,
    GameChatData,
    PlayerData,
)

from ..notifier import clocks_payload, result_status
from .board import BughouseBoards
from .models import ChatRecord, GameObj, pos_for, team_of_pos


@dataclass(slots=True)
class _PlayerView:
    username: str
    rating: float


def _last_move_to_squares(uci: str | None) -> tuple[str, str] | tuple[str] | None:
    if uci is None:
        return None
    if "@" in uci:
        return (uci.split("@", 1)[1],)
    a = uci[:2]
    b = uci[2:4]
    if not a or not b:
        return None
    return (a, b)


def _chat_payload(record: ChatRecord) -> GameChatData:
    return GameChatData(
        idx=record.idx,
        username=record.username,
        text=record.text,
        created_at=record.created_at,
    )


def _board_data(
    boards: BughouseBoards,
    board_idx: int,
    white: _PlayerView,
    black: _PlayerView,
    clocks: ClocksData,
    auto_abort_at: int | None,
) -> BoardData:
    fen = boards.fen(board_idx)
    if board_idx == 0:
        white_clock_time, black_clock_time = clocks.b0w, clocks.b0b
    else:
        white_clock_time, black_clock_time = clocks.b1w, clocks.b1b
    return BoardData(
        fen=fen,
        players=(
            PlayerData(
                name=white.username,
                rating=white.rating,
                color="white",
                clock_time=white_clock_time,
            ),
            PlayerData(
                name=black.username,
                rating=black.rating,
                color="black",
                clock_time=black_clock_time,
            ),
        ),
        last_move=_last_move_to_squares(boards.last_move(board_idx)),
        auto_abort_at=auto_abort_at,
    )


def build_bughouse(game: GameObj, viewer_username: str | None = None) -> BughouseData:
    clocks = clocks_payload(game.clocks.snapshot())
    refs = [_PlayerView(p.username, p.rating_before) for p in game.players]

    b0_white = refs[pos_for(0, chess.WHITE, game.color_flip)]
    b0_black = refs[pos_for(0, chess.BLACK, game.color_flip)]
    b1_white = refs[pos_for(1, chess.WHITE, game.color_flip)]
    b1_black = refs[pos_for(1, chess.BLACK, game.color_flip)]

    board0 = _board_data(
        game.boards, 0, b0_white, b0_black, clocks, game.auto_abort_at.get(0)
    )
    board1 = _board_data(
        game.boards, 1, b1_white, b1_black, clocks, game.auto_abort_at.get(1)
    )
    status = result_status(game.result) if game.result is not None else None
    chat: list[GameChatData] = []
    if viewer_username is not None:
        team = team_of_pos(game.pos_of(viewer_username))
        chat = [_chat_payload(record) for record in game.chat[team]]
    return BughouseData(
        boards=(board0, board1),
        incr=game.config.incr,
        auto_abort_timeout=game.auto_abort_timeout,
        status=status,
        chat=chat,
    )
