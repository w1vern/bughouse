from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import chess

from shared.infrastructure import setup_logger

logger = setup_logger(__name__)

FlagCallback = Callable[[int, chess.Color], Awaitable[None]]


def _key_name(board_idx: int, color: chess.Color) -> str:
    side = "w" if color == chess.WHITE else "b"
    return f"b{board_idx}{side}"


class Clocks:
    __slots__ = ("ms", "_active", "_lock", "_shutdown")

    def __init__(self, initial_ms: int) -> None:
        self.ms: dict[tuple[int, chess.Color], int] = {
            (0, chess.WHITE): initial_ms,
            (0, chess.BLACK): initial_ms,
            (1, chess.WHITE): initial_ms,
            (1, chess.BLACK): initial_ms,
        }
        self._active: dict[int, tuple[chess.Color, asyncio.Task[None], float]] = {}
        self._lock = asyncio.Lock()
        self._shutdown = False

    async def start(
        self,
        board_idx: int,
        color: chess.Color,
        on_flag: FlagCallback,
    ) -> None:
        async with self._lock:
            if self._shutdown:
                return
            remaining = self.ms[(board_idx, color)]
            started_at = time.monotonic()
            task = asyncio.create_task(
                self._watchdog(board_idx, color, remaining, on_flag)
            )
            self._active[board_idx] = (color, task, started_at)

    async def stop_and_apply(self, board_idx: int, increment_ms: int) -> int:
        async with self._lock:
            entry = self._active.pop(board_idx, None)
            if entry is None:
                return 0
            color, task, started_at = entry
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        async with self._lock:
            current = self.ms[(board_idx, color)]
            new_val = current - elapsed_ms + increment_ms
            if new_val < 0:
                new_val = 0
            self.ms[(board_idx, color)] = new_val
            return elapsed_ms

    async def shutdown(self) -> None:
        async with self._lock:
            self._shutdown = True
            active = list(self._active.values())
            self._active.clear()
        for _color, task, _ in active:
            task.cancel()
        for _color, task, _ in active:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    def snapshot(self) -> dict[str, int]:
        now = time.monotonic()
        out: dict[str, int] = {}
        for (board_idx, color), base_ms in self.ms.items():
            active = self._active.get(board_idx)
            if active is not None and active[0] == color:
                elapsed = int((now - active[2]) * 1000)
                remaining = base_ms - elapsed
                if remaining < 0:
                    remaining = 0
                out[_key_name(board_idx, color)] = remaining
            else:
                out[_key_name(board_idx, color)] = base_ms
        return out

    async def _watchdog(
        self,
        board_idx: int,
        color: chess.Color,
        remaining_ms: int,
        on_flag: FlagCallback,
    ) -> None:
        try:
            await asyncio.sleep(remaining_ms / 1000)
        except asyncio.CancelledError:
            raise
        me = asyncio.current_task()
        async with self._lock:
            entry = self._active.get(board_idx)
            if entry is None or entry[0] != color or entry[1] is not me:
                return
            self._active.pop(board_idx, None)
            self.ms[(board_idx, color)] = 0
        try:
            await on_flag(board_idx, color)
        except Exception:
            logger.exception("on_flag callback failed")
