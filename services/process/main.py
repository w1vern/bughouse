from __future__ import annotations

from typing import Protocol

from shared.infrastructure import setup_logger
from shared.protobuf import process_pb2 as pb
from shared.protobuf import process_pb2_grpc

from .errors import GameError, LobbyError, ProcessError, QueueError
from .notifier import Notifier
from .pb_builders import build_game_state, build_lobby_state
from .session import UserSessionIndex

logger = setup_logger(__name__)


class _LobbyManager(Protocol):
    async def create(self, user_id: str) -> object: ...
    async def join(self, user_id: str, lobby_id: str) -> object: ...
    async def leave(self, user_id: str) -> None: ...
    async def seat(self, leader_id: str, target_user_id: str, pos: int) -> None: ...
    async def unseat(self, leader_id: str, pos: int) -> None: ...
    async def kick(self, leader_id: str, target_user_id: str) -> None: ...
    async def set_config(self, leader_id: str, initial_ms: int, increment_ms: int, rated: bool) -> None: ...
    def get_by_id(self, lobby_id: str) -> object | None: ...
    def get_by_user(self, user_id: str) -> object | None: ...


class _QueueManager(Protocol):
    async def start(self, user_id: str) -> None: ...
    async def cancel(self, user_id: str) -> None: ...


class _GameManager(Protocol):
    async def make_move(self, user_id: str, uci: str) -> None: ...
    async def resign(self, user_id: str) -> None: ...
    def get_by_user(self, user_id: str) -> object | None: ...


def _status_from_error(e: ProcessError) -> pb.StatusResp:
    return pb.StatusResp(ok=False, error_code=e.code, message=e.message)


def _lobby_error_resp(e: ProcessError) -> pb.LobbyResp:
    return pb.LobbyResp(ok=False, error_code=e.code, message=e.message)


class ProcessServiceServicer(process_pb2_grpc.ProcessServiceServicer):
    def __init__(
        self,
        lobbies: _LobbyManager,
        queue: _QueueManager,
        games: _GameManager,
        notifier: Notifier,
        sessions: UserSessionIndex,
    ) -> None:
        self.lobbies = lobbies
        self.queue = queue
        self.games = games
        self.notifier = notifier
        self.sessions = sessions

    # ---------------- Lobby ----------------

    async def CreateLobby(self, request: pb.UserRef, context) -> pb.LobbyResp:
        try:
            lobby = await self.lobbies.create(request.user_id)
        except LobbyError as e:
            return _lobby_error_resp(e)
        return pb.LobbyResp(ok=True, lobby_id=lobby.id)  # type: ignore[attr-defined]

    async def JoinLobby(self, request: pb.JoinReq, context) -> pb.LobbyResp:
        try:
            lobby = await self.lobbies.join(request.user_id, request.lobby_id)
        except LobbyError as e:
            return _lobby_error_resp(e)
        return pb.LobbyResp(ok=True, lobby_id=lobby.id)  # type: ignore[attr-defined]

    async def LeaveLobby(self, request: pb.UserRef, context) -> pb.StatusResp:
        try:
            await self.lobbies.leave(request.user_id)
        except LobbyError as e:
            return _status_from_error(e)
        return pb.StatusResp(ok=True)

    async def SeatPlayer(self, request: pb.SeatReq, context) -> pb.StatusResp:
        try:
            await self.lobbies.seat(request.leader_id, request.target_user_id, request.pos)
        except LobbyError as e:
            return _status_from_error(e)
        return pb.StatusResp(ok=True)

    async def UnseatPlayer(self, request: pb.UnseatReq, context) -> pb.StatusResp:
        try:
            await self.lobbies.unseat(request.leader_id, request.pos)
        except LobbyError as e:
            return _status_from_error(e)
        return pb.StatusResp(ok=True)

    async def KickFromLobby(self, request: pb.KickReq, context) -> pb.StatusResp:
        try:
            await self.lobbies.kick(request.leader_id, request.target_user_id)
        except LobbyError as e:
            return _status_from_error(e)
        return pb.StatusResp(ok=True)

    async def SetLobbyConfig(self, request: pb.SetConfigReq, context) -> pb.StatusResp:
        try:
            await self.lobbies.set_config(
                request.leader_id,
                request.initial_ms,
                request.increment_ms,
                request.rated,
            )
        except LobbyError as e:
            return _status_from_error(e)
        return pb.StatusResp(ok=True)

    async def StartMatchmaking(self, request: pb.UserRef, context) -> pb.StatusResp:
        try:
            await self.queue.start(request.user_id)
        except (QueueError, LobbyError) as e:
            return _status_from_error(e)
        return pb.StatusResp(ok=True)

    async def CancelMatchmaking(self, request: pb.UserRef, context) -> pb.StatusResp:
        try:
            await self.queue.cancel(request.user_id)
        except (QueueError, LobbyError) as e:
            return _status_from_error(e)
        return pb.StatusResp(ok=True)

    async def GetLobby(self, request: pb.LobbyRef, context) -> pb.LobbyStateResp:
        lobby = self.lobbies.get_by_id(request.lobby_id)
        if lobby is None:
            return pb.LobbyStateResp(ok=False, error_code="lobby_not_found", message="Lobby not found")
        return pb.LobbyStateResp(ok=True, lobby=build_lobby_state(lobby))  # type: ignore[arg-type]

    # ---------------- Game ----------------

    async def MakeMove(self, request: pb.MoveReq, context) -> pb.StatusResp:
        try:
            await self.games.make_move(request.user_id, request.uci)
        except GameError as e:
            return _status_from_error(e)
        return pb.StatusResp(ok=True)

    async def Resign(self, request: pb.UserRef, context) -> pb.StatusResp:
        try:
            await self.games.resign(request.user_id)
        except GameError as e:
            return _status_from_error(e)
        return pb.StatusResp(ok=True)

    async def GetGameState(self, request: pb.UserRef, context) -> pb.GameStateResp:
        game = self.games.get_by_user(request.user_id)
        if game is None:
            return pb.GameStateResp(ok=False, error_code="game_not_found", message="No active game for user")
        return pb.GameStateResp(ok=True, game=build_game_state(game, request.user_id))  # type: ignore[arg-type]

    # ---------------- Session ----------------

    async def GetUserSnapshot(self, request: pb.UserRef, context) -> pb.SnapshotResp:
        return self.sessions.get_snapshot(request.user_id)
