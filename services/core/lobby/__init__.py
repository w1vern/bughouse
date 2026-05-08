from __future__ import annotations

from typing import TYPE_CHECKING

from .errors import LobbyError
from .models import Lobby, LobbyConfig, LobbyState, Seat

if TYPE_CHECKING:
    from .manager import LobbyManager, UserRepoFactory

__all__ = [
    "Lobby",
    "LobbyConfig",
    "LobbyError",
    "LobbyManager",
    "LobbyState",
    "Seat",
    "UserRepoFactory",
]


def __getattr__(name: str) -> object:
    if name == "LobbyManager":
        from .manager import LobbyManager

        return LobbyManager
    if name == "UserRepoFactory":
        from .manager import UserRepoFactory

        return UserRepoFactory
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
