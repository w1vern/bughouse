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


class BotEngine:
    """Pool of Fairy-Stockfish processes shared across all bot games.

    - Which bots use the engine is held in memory (`_engine_on`) and refreshed
      from Redis via `sync()`, triggered by the backend over gRPC. The per-move
      decision reads this in-memory set (no Redis call per move).
    - The process pool is started lazily and torn down once no bot has the
      engine enabled, so it does not occupy memory when unused.
    - If the binary is missing or all workers are busy, `choose` returns None and
      the caller falls back to a random move.
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

    async def _load(self) -> None:
        if not os.path.exists(ENGINE_BINARY_PATH):
            logger.warning(
                "engine binary %s not found; bots will play random moves",
                ENGINE_BINARY_PATH,
            )
            return
        queue: asyncio.Queue[chess.engine.UciProtocol] = asyncio.Queue()
        pool: list[chess.engine.UciProtocol] = []
        try:
            for _ in range(max(1, self._settings.pool_size)):
                _transport, engine = await chess.engine.popen_uci(ENGINE_BINARY_PATH)
                pool.append(engine)
                queue.put_nowait(engine)
        except Exception:
            logger.exception("failed to start engine pool at %s", ENGINE_BINARY_PATH)
            for engine in pool:
                try:
                    await engine.quit()
                except Exception:
                    pass
            return
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

    async def choose(
        self,
        name: str,
        skill_level: int,
        board: chess.Board,
        white_ms: int,
        black_ms: int,
        inc_ms: int,
    ) -> str | None:
        if name not in self._engine_on or not self._loaded:
            return None
        queue = self._available
        if queue is None:
            return None
        try:
            engine = queue.get_nowait()
        except asyncio.QueueEmpty:
            # All workers busy — fall back to random for this move.
            return None
        try:
            if not self._loaded:
                return None
            limit = chess.engine.Limit(
                white_clock=max(0, white_ms) / 1000,
                black_clock=max(0, black_ms) / 1000,
                white_inc=inc_ms / 1000,
                black_inc=inc_ms / 1000,
            )
            result = await asyncio.wait_for(
                engine.play(
                    board, limit, options={"Skill Level": int(skill_level)}
                ),
                timeout=self._settings.max_think_ms / 1000 + 5.0,
            )
            return result.move.uci() if result.move is not None else None
        except Exception:
            logger.exception("engine play failed for bot %s", name)
            return None
        finally:
            queue.put_nowait(engine)

    async def shutdown(self) -> None:
        async with self._lock:
            if self._loaded:
                await self._unload()
