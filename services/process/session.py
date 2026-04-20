from __future__ import annotations

from typing import Protocol

from shared.protobuf import process_pb2 as pb

from .pb_builders import build_game_state, build_lobby_state


class _LobbyManager(Protocol):
    def get_by_user(self, user_id: str) -> object | None: ...


class _GameManager(Protocol):
    def get_by_user(self, user_id: str) -> object | None: ...


class UserSessionIndex:
    def __init__(self, lobbies: _LobbyManager, games: _GameManager) -> None:
        self._lobbies = lobbies
        self._games = games

    def get_snapshot(self, user_id: str) -> pb.SnapshotResp:
        game = self._games.get_by_user(user_id)
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
