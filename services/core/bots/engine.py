from __future__ import annotations

import asyncio
import os

import chess
import chess.engine
from redis.asyncio import Redis

from shared.infrastructure import EngineSettings, setup_logger

logger = setup_logger(__name__)

# Redis set of bot names whose engine is enabled (backend writes, core reads).
ENGINE_ON_KEY = "bot:engine_on"

# Fixed location of the Fairy-Stockfish binary baked into the image (Dockerfile).
# If it is absent (e.g. local dev outside Docker), bots play random moves.
ENGINE_BINARY_PATH = "/usr/local/bin/fairy-stockfish"

# Extra slack on top of the per-move think budget before a search is considered
# hung. A healthy search returns within the budget; this only fires on a real
# stall, and when it does the worker is retired (never reused) because a
# cancelled UCI search leaves the process desynced.
_HANG_GUARD_S = 5.0


class BotEngine:
    """Pool of Fairy-Stockfish processes shared across all bot games.

    - Which bots use the engine is held in memory (`_engine_on`) and refreshed
      from Redis via `sync()`, triggered by the backend over gRPC. The per-move
      decision reads this in-memory set (no Redis call per move).
    - The process pool is started lazily and torn down once no bot has the
      engine enabled, so it does not occupy memory when unused.
    - Each move is given a bounded think time (clock-aware, hard-capped by
      `max_think_ms`) and passed as a fixed search time, so a generous game
      clock can never pin a worker for many seconds and a search always
      returns before the hang guard. If a search does error or stall, the
      worker is retired and replaced so the pool can't be poisoned.
    - If the binary is missing or all workers are busy, `choose` returns None
      and the caller falls back to a random move.
    """

    def __init__(self, redis: Redis, settings: EngineSettings) -> None:
        self._redis = redis
        self._settings = settings
        self._engine_on: set[str] = set()
        self._pool: list[chess.engine.UciProtocol] = []
        self._available: asyncio.Queue[chess.engine.UciProtocol] | None = None
        self._loaded = False
        self._lock = asyncio.Lock()

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def max_think_ms(self) -> int:
        return self._settings.max_think_ms

    def is_engine_on(self, name: str) -> bool:
        return name in self._engine_on

    async def sync(self) -> None:
        """Refresh the engine-on set from Redis and (un)load the pool."""
        self._engine_on = await self._read_engine_on()
        async with self._lock:
            if self._engine_on and not self._loaded:
                await self._load()
            elif not self._engine_on and self._loaded:
                await self._unload()

    async def _read_engine_on(self) -> set[str]:
        try:
            members = await self._redis.smembers(ENGINE_ON_KEY)  # type: ignore[misc]
        except Exception:
            logger.exception("failed reading %s", ENGINE_ON_KEY)
            return set()
        return {m.decode() if isinstance(m, bytes) else m for m in members}

    async def _spawn_one(self) -> chess.engine.UciProtocol | None:
        try:
            _transport, engine = await chess.engine.popen_uci(ENGINE_BINARY_PATH)
            return engine
        except Exception:
            logger.exception("failed to start engine at %s", ENGINE_BINARY_PATH)
            return None

    async def _load(self) -> None:
        if not os.path.exists(ENGINE_BINARY_PATH):
            logger.warning(
                "engine binary %s not found; bots will play random moves",
                ENGINE_BINARY_PATH,
            )
            return
        queue: asyncio.Queue[chess.engine.UciProtocol] = asyncio.Queue()
        pool: list[chess.engine.UciProtocol] = []
        for _ in range(max(1, self._settings.pool_size)):
            engine = await self._spawn_one()
            if engine is None:
                for started in pool:
                    try:
                        await started.quit()
                    except Exception:
                        pass
                return
            pool.append(engine)
            queue.put_nowait(engine)
        self._pool = pool
        self._available = queue
        self._loaded = True
        logger.info("engine pool loaded (%d workers)", len(pool))

    async def _unload(self) -> None:
        self._loaded = False
        queue = self._available
        engines = list(self._pool)
        self._available = None
        self._pool = []
        # Wait for any in-flight searches to return their worker before quitting.
        if queue is not None:
            for _ in range(len(engines)):
                await queue.get()
        for engine in engines:
            try:
                await engine.quit()
            except Exception:
                pass
        logger.info("engine pool unloaded")

    async def _retire(
        self,
        engine: chess.engine.UciProtocol,
        queue: asyncio.Queue[chess.engine.UciProtocol],
    ) -> None:
        """Drop a possibly-desynced worker and refill the pool to keep its size.

        A cancelled or errored UCI search can leave the process returning stale
        best moves, so the worker is never reused; instead it is quit and a
        fresh process takes its slot (unless the pool is being torn down).
        """
        try:
            self._pool.remove(engine)
        except ValueError:
            pass
        try:
            await engine.quit()
        except Exception:
            pass
        if not self._loaded:
            return
        replacement = await self._spawn_one()
        if replacement is not None:
            self._pool.append(replacement)
            queue.put_nowait(replacement)

    async def choose(
        self,
        name: str,
        skill_level: int,
        board: chess.Board,
        think_time_s: float,
    ) -> str | None:
        """Search ``board`` for ``think_time_s`` seconds and return a UCI move.

        Time management (clock awareness, the per-move ceiling) is decided by the
        caller; here we just search for the given time. Returns None if disabled,
        all workers are busy, there is no legal move, or the search errors.
        """
        if name not in self._engine_on or not self._loaded:
            return None
        if not any(board.legal_moves):
            return None
        queue = self._available
        if queue is None:
            return None
        try:
            engine = queue.get_nowait()
        except asyncio.QueueEmpty:
            # All workers busy — fall back to random for this move.
            return None

        # Drive the engine from a stackless copy so python-chess sends the full
        # position as a FEN (`position fen ...[pocket]...`) instead of a move
        # list. In bughouse the pockets are fed across the two boards, so they
        # do not match a crazyhouse replay of this board's own moves; a move
        # list would desync the engine's pockets from reality and make it return
        # illegal or nonsense moves (and silently fall back to random). The FEN
        # carries the true pockets, so the engine sees the real position.
        search_board = board.copy(stack=False)

        budget_s = max(0.05, think_time_s)
        healthy = False
        try:
            result = await asyncio.wait_for(
                engine.play(
                    search_board,
                    chess.engine.Limit(time=budget_s),
                    options={"Skill Level": int(skill_level)},
                ),
                timeout=budget_s + _HANG_GUARD_S,
            )
            healthy = True
            return result.move.uci() if result.move is not None else None
        except Exception:
            logger.exception("engine play failed for bot %s", name)
            return None
        finally:
            if healthy and self._loaded:
                queue.put_nowait(engine)
            else:
                await self._retire(engine, queue)

    async def shutdown(self) -> None:
        async with self._lock:
            if self._loaded:
                await self._unload()
