from __future__ import annotations

import random
from typing import Protocol

import chess


class MovePolicy(Protocol):
    """Chooses a bot's move on a single board.

    Stage 1 ships :class:`RandomMovePolicy`. Stage 2 will add an engine-backed
    policy (e.g. Fairy-Stockfish) implementing the same interface, selected per
    bot from its ``engine_enabled`` / ``strength`` settings.
    """

    def choose(self, board: chess.Board) -> str | None:
        """Return a legal move in UCI form, or ``None`` if there is none."""
        ...


class RandomMovePolicy:
    def choose(self, board: chess.Board) -> str | None:
        moves = list(board.legal_moves)
        if not moves:
            return None
        return random.choice(moves).uci()
