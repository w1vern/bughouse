from __future__ import annotations

from uuid import UUID

from shared.protobuf import process_pb2 as pb

from .game.manager import GameManager
from .lobby.manager import LobbyManager
from .pb_builders import build_game_state, build_lobby_state


class UserSessionIndex:
    def __init__(self, lobbies: LobbyManager, games: GameManager) -> None:
        self._lobbies = lobbies
        self._games = games

    def get_snapshot(self, user_id: UUID) -> pb.SnapshotResp:
        game = self._games.get_game_by_user(user_id)
        if game is not None:
            return pb.SnapshotResp(
                ok=True,
                state="GAME",
                game=build_game_state(game, user_id),
            )
        lobby = self._lobbies.get_by_user(user_id)
        if lobby is not None:
            return pb.SnapshotResp(
                ok=True,
                state="LOBBY",
                lobby=build_lobby_state(lobby),
            )
        return pb.SnapshotResp(ok=True, state="IDLE")
