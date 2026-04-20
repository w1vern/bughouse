"""Smoke-stubs used while lobby/queue/game managers (tasks 2-4) are not implemented.

Заглушки нужны только для того, чтобы __main__.py поднимал gRPC-сервер и его
можно было проверять руками. Любой RPC, требующий реальной логики, вернёт
ошибку *_error. При готовых менеджерах этот файл удаляется (и блок ImportError
в __main__.py падает на реальные импорты).
"""

from __future__ import annotations

import asyncio
from typing import Any

from .errors import GameError, LobbyError, QueueError


class LobbyManager:
    def __init__(self, **_: Any) -> None:
        pass

    async def create(self, user_id: str) -> Any:
        raise LobbyError("LobbyManager not implemented", code="not_implemented")

    async def join(self, user_id: str, lobby_id: str) -> Any:
        raise LobbyError("LobbyManager not implemented", code="not_implemented")

    async def leave(self, user_id: str) -> None:
        raise LobbyError("LobbyManager not implemented", code="not_implemented")

    async def seat(self, leader_id: str, target_user_id: str, pos: int) -> None:
        raise LobbyError("LobbyManager not implemented", code="not_implemented")

    async def unseat(self, leader_id: str, pos: int) -> None:
        raise LobbyError("LobbyManager not implemented", code="not_implemented")

    async def kick(self, leader_id: str, target_user_id: str) -> None:
        raise LobbyError("LobbyManager not implemented", code="not_implemented")

    async def set_config(self, leader_id: str, initial_ms: int, increment_ms: int, rated: bool) -> None:
        raise LobbyError("LobbyManager not implemented", code="not_implemented")

    def get_by_id(self, lobby_id: str) -> Any:
        return None

    def get_by_user(self, user_id: str) -> Any:
        return None


class QueueManager:
    def __init__(self, **_: Any) -> None:
        self._stop = asyncio.Event()

    async def start(self, user_id: str) -> None:
        raise QueueError("QueueManager not implemented", code="not_implemented")

    async def cancel(self, user_id: str) -> None:
        raise QueueError("QueueManager not implemented", code="not_implemented")

    async def start_loop(self) -> None:
        await self._stop.wait()

    async def stop_loop(self) -> None:
        self._stop.set()


class GameManager:
    def __init__(self, **_: Any) -> None:
        pass

    async def make_move(self, user_id: str, uci: str) -> None:
        raise GameError("GameManager not implemented", code="not_implemented")

    async def resign(self, user_id: str) -> None:
        raise GameError("GameManager not implemented", code="not_implemented")

    def get_by_user(self, user_id: str) -> Any:
        return None

    async def drop_all(self) -> None:
        return None
