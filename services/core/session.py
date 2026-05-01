from __future__ import annotations

from shared.events import SyncData

from .game.manager import GameManager
from .game.state import build_bughouse
from .lobby.manager import LobbyManager
from .notifier import lobby_data


class UserSessionIndex:
    def __init__(self, lobbies: LobbyManager, games: GameManager) -> None:
        self._lobbies = lobbies
        self._games = games

    def get_sync(self, username: str) -> SyncData:
        game = self._games.get_game_by_user(username)
        if game is not None:
            return SyncData(
                state="GAME",
                lobby=None,
                game=build_bughouse(game),
            )
        lobby = self._lobbies.get_by_user(username)
        if lobby is not None:
            return SyncData(
                state="LOBBY",
                lobby=lobby_data(lobby),
                game=None,
            )
        return SyncData(state="IDLE", lobby=None, game=None)
