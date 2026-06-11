from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import chess
import chess.variant

from services.core.bots.engine import BotEngine
from shared.infrastructure import EngineSettings


class _RecordingEngine:
    """Stands in for a Fairy-Stockfish worker; records the board it is asked to
    search and plays the first legal move."""

    def __init__(self) -> None:
        self.boards: list[chess.Board] = []

    async def play(self, board, limit, options=None):  # type: ignore[no-untyped-def]
        self.boards.append(board)
        move = next(iter(board.legal_moves))
        return SimpleNamespace(move=move)


def _cross_fed_board() -> chess.variant.CrazyhouseBoard:
    """A board whose pocket was fed from the *other* board, so its pocket no
    longer matches a crazyhouse replay of its own moves (the bughouse case)."""
    board = chess.variant.CrazyhouseBoard()
    for uci in ("e2e4", "d7d5", "e4d5", "d8d5"):
        board.push_uci(uci)
    # Crazyhouse auto-gave white the captured pawn; in bughouse it goes to the
    # partner instead, and white is handed a knight a partner captured.
    board.pockets[chess.WHITE].remove(chess.PAWN)
    board.pockets[chess.WHITE].add(chess.KNIGHT)
    return board


class BotEngineChooseTests(unittest.IsolatedAsyncioTestCase):
    async def _engine_with_worker(self, worker: _RecordingEngine) -> BotEngine:
        engine = BotEngine(
            redis=AsyncMock(),
            settings=EngineSettings(pool_size=1, max_think_ms=500),
        )
        engine._engine_on = {"bot"}
        engine._loaded = True
        queue: asyncio.Queue = asyncio.Queue()
        queue.put_nowait(worker)  # type: ignore[arg-type]
        engine._available = queue
        engine._pool = [worker]  # type: ignore[list-item]
        return engine

    async def test_choose_searches_stackless_board_with_true_pocket(self) -> None:
        worker = _RecordingEngine()
        engine = await self._engine_with_worker(worker)
        board = _cross_fed_board()

        uci = await engine.choose("bot", 20, board, 0.3)

        self.assertIsNotNone(uci)
        sent = worker.boards[0]
        # No move stack -> python-chess sends `position fen ...`, not a move list
        # that would let the engine recompute (wrong) pockets.
        self.assertEqual(len(sent.move_stack), 0)
        # The true cross-fed pocket (a knight, not the captured pawn) is carried.
        self.assertEqual(str(sent.pockets[chess.WHITE]), "n")
        # The chosen move is legal in the real board.
        self.assertTrue(board.is_legal(board.parse_uci(uci)))  # type: ignore[arg-type]

    async def test_choose_returns_none_when_no_legal_move(self) -> None:
        worker = _RecordingEngine()
        engine = await self._engine_with_worker(worker)
        # Distant-check mate with empty pocket: no legal move (sitting in bughouse).
        board = chess.variant.CrazyhouseBoard()
        for uci in ("f2f3", "e7e5", "g2g4", "d8h4"):
            board.push_uci(uci)

        uci = await engine.choose("bot", 20, board, 0.3)

        self.assertIsNone(uci)
        self.assertEqual(worker.boards, [])  # engine never invoked


if __name__ == "__main__":
    unittest.main()
