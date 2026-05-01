from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import chess
import chess.variant

PIECE_SYMBOL = {
    chess.PAWN: "P",
    chess.KNIGHT: "N",
    chess.BISHOP: "B",
    chess.ROOK: "R",
    chess.QUEEN: "Q",
    chess.KING: "K",
}

PocketDict = dict[str, int]
BoardPockets = dict[str, PocketDict]
PocketsDict = dict[str, BoardPockets]


@dataclass(slots=True)
class ApplyResult:
    move: chess.Move
    board_idx: int
    mover_color: chess.Color
    captured: chess.PieceType | None
    captured_promoted: bool
    fen_after: str
    pockets_after: PocketsDict


class BughouseBoards:
    __slots__ = ("boards", "_last_move")

    def __init__(self) -> None:
        self.boards: tuple[chess.variant.CrazyhouseBoard, chess.variant.CrazyhouseBoard] = (
            chess.variant.CrazyhouseBoard(),
            chess.variant.CrazyhouseBoard(),
        )
        self._last_move: dict[int, str | None] = {0: None, 1: None}

    def turn(self, board_idx: int) -> chess.Color:
        return self.boards[board_idx].turn

    def push(self, board_idx: int, uci: str) -> ApplyResult:
        board = self.boards[board_idx]
        mover = board.turn
        move = board.parse_uci(uci)
        if not board.is_legal(move):
            raise chess.IllegalMoveError(f"illegal move {uci}")

        captured_type: chess.PieceType | None = None
        captured_promoted = False
        if move.drop is None:
            if board.is_en_passant(move):
                captured_type = chess.PAWN
                captured_promoted = False
            else:
                piece = board.piece_at(move.to_square)
                if piece is not None:
                    captured_type = piece.piece_type
                    captured_promoted = bool(
                        board.promoted & chess.BB_SQUARES[move.to_square]
                    )

        board.push(move)

        if captured_type is not None:
            effective_type = chess.PAWN if captured_promoted else captured_type
            own_pocket = board.pockets[mover]
            partner_pocket = self.boards[1 - board_idx].pockets[not mover]

            own_pocket.remove(effective_type)

            partner_pocket.add(effective_type)

        self._last_move[board_idx] = uci

        return ApplyResult(
            move=move,
            board_idx=board_idx,
            mover_color=mover,
            captured=captured_type,
            captured_promoted=captured_promoted,
            fen_after=board.fen(),
            pockets_after=self._all_pockets(),
        )

    def is_checkmate(self, board_idx: int) -> bool:
        return self.boards[board_idx].is_checkmate()

    def is_draw_rule(self) -> bool:
        for b in self.boards:
            if b.is_fivefold_repetition() or b.is_seventyfive_moves():
                return True
        return False

    def last_move(self, board_idx: int) -> str | None:
        return self._last_move[board_idx]

    def fen(self, board_idx: int) -> str:
        return self.boards[board_idx].fen()

    def _pocket_to_dict(
        self, pocket: chess.variant.CrazyhousePocket
    ) -> PocketDict:
        return {
            symbol: pocket.count(pt)
            for pt, symbol in PIECE_SYMBOL.items()
            if pt != chess.KING and pocket.count(pt) > 0
        }

    def board_pockets(self, board_idx: int) -> BoardPockets:
        b = self.boards[board_idx]
        return {
            "w": self._pocket_to_dict(b.pockets[chess.WHITE]),
            "b": self._pocket_to_dict(b.pockets[chess.BLACK]),
        }

    def _all_pockets(self) -> PocketsDict:
        return {"b0": self.board_pockets(0), "b1": self.board_pockets(1)}

    def to_snapshot(self, pov_board_idx: int) -> dict[str, Any]:
        partner_idx = 1 - pov_board_idx
        return {
            "fen": self.fen(pov_board_idx),
            "mate_fen": self.fen(partner_idx),
            "pockets": self._all_pockets(),
            "last_move": self._last_move[pov_board_idx],
        }
