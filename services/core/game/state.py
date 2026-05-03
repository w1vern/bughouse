from __future__ import annotations

from dataclasses import dataclass

from shared.events import (
    BoardData,
    BughouseData,
    ClocksData,
    PlayerData,
    PocketData,
)

from ..notifier import clocks_payload, now, result_status
from .board import BughouseBoards, PocketDict
from .models import GameObj


_PIECE_LETTER_TO_NAME = {
    "P": "pawn",
    "N": "knight",
    "B": "bishop",
    "R": "rook",
    "Q": "queen",
}


@dataclass(slots=True)
class _PlayerView:
    username: str
    rating: float


def _pocket_payload(pocket: PocketDict) -> PocketData:
    counts = {_PIECE_LETTER_TO_NAME[k]: v for k, v in pocket.items()}
    return PocketData(**counts)


def _last_move_to_squares(uci: str | None) -> tuple[str, str] | tuple[str] | None:
    if uci is None:
        return None
    if "@" in uci:
        # drop move "P@e4" → ("e4",)
        return (uci.split("@", 1)[1],)
    a = uci[:2]
    b = uci[2:4]
    if not a or not b:
        return None
    return (a, b)


def _board_data(
    boards: BughouseBoards,
    board_idx: int,
    white: _PlayerView,
    black: _PlayerView,
    clocks: ClocksData,
) -> BoardData:
    fen = boards.fen(board_idx)
    pockets = boards.board_pockets(board_idx)
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
                pocket=_pocket_payload(pockets["w"]),
            ),
            PlayerData(
                name=black.username,
                rating=black.rating,
                color="black",
                clock_time=black_clock_time,
                pocket=_pocket_payload(pockets["b"]),
            ),
        ),
        last_move=_last_move_to_squares(boards.last_move(board_idx)),
    )


def build_bughouse(game: GameObj) -> BughouseData:
    clocks = clocks_payload(game.clocks.snapshot())
    refs = [
        _PlayerView(p.username, p.rating_before) for p in game.players
    ]
    board0 = _board_data(game.boards, 0, refs[0], refs[1], clocks)
    board1 = _board_data(game.boards, 1, refs[2], refs[3], clocks)
    status = result_status(game.result) if game.result is not None else None
    return BughouseData(
        boards=(board0, board1),
        status=status,
        timestamp=now(),
    )
