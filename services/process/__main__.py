from __future__ import annotations

import asyncio
import contextlib
import signal
from collections.abc import AsyncIterator
from typing import Any

import grpc
from grpc import aio

from shared.database.main import session_manager
from shared.database.repositories.user import UserRepository
from shared.infrastructure import env_config, get_redis_client, setup_logger
from shared.protobuf import process_pb2_grpc

from .main import ProcessServiceServicer
from .notifier import Notifier
from .session import UserSessionIndex

logger = setup_logger(__name__)


@contextlib.asynccontextmanager
async def _user_repo_ctx() -> AsyncIterator[UserRepository]:
    async with session_manager.context_session() as session:
        yield UserRepository(session)


async def _build_managers(notifier: Notifier) -> tuple[Any, Any, Any]:
    """Инстансирует LobbyManager / QueueManager / GameManager.

    Менеджеры (задачи 2-4) подключаются здесь. Пока они не реализованы —
    импорт оборачиваем в try/except, чтобы сервер всё равно поднимался в
    smoke-режиме с заглушками.
    """
    try:
        from .lobby.manager import LobbyManager  # type: ignore[attr-defined]
        from .queue.manager import QueueManager  # type: ignore[attr-defined]
        from .game.manager import GameManager    # type: ignore[attr-defined]
    except ImportError:
        logger.warning("Менеджеры ещё не реализованы (задачи 2-4). Поднимаю с заглушками.")
        from ._stubs import GameManager, LobbyManager, QueueManager

    lobby_mgr = LobbyManager(notifier=notifier, user_repo_factory=_user_repo_ctx)
    game_mgr = GameManager(
        notifier=notifier,
        user_repo_factory=_user_repo_ctx,
        abort_timeout_sec=env_config.process.abort_timeout_sec,
    )
    queue_mgr = QueueManager(
        lobbies=lobby_mgr,
        games=game_mgr,
        notifier=notifier,
        tick_sec=env_config.process.queue_tick_sec,
    )
    return lobby_mgr, queue_mgr, game_mgr


async def main() -> None:
    redis = get_redis_client(env_config.redis.backend)
    notifier = Notifier(redis)

    lobby_mgr, queue_mgr, game_mgr = await _build_managers(notifier)
    sessions = UserSessionIndex(lobby_mgr, game_mgr)

    queue_task = asyncio.create_task(queue_mgr.start_loop())

    server = aio.server()
    process_pb2_grpc.add_ProcessServiceServicer_to_server(
        ProcessServiceServicer(lobby_mgr, queue_mgr, game_mgr, notifier, sessions),
        server,
    )
    bind = f"0.0.0.0:{env_config.process.grpc_port}"
    server.add_insecure_port(bind)
    await server.start()
    logger.info("gRPC server started on %s", bind)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _handle_signal() -> None:
        logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            # Windows: без POSIX-сигналов полагаемся на KeyboardInterrupt
            pass

    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("Stopping queue loop")
        await queue_mgr.stop_loop()
        queue_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await queue_task

        logger.info("Stopping gRPC server")
        await server.stop(grace=5)

        logger.info("Dropping active games")
        await game_mgr.drop_all()

        logger.info("Closing Redis and DB")
        await redis.aclose()
        await session_manager.close()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
