from __future__ import annotations

from uuid import UUID

import grpc

from shared.infrastructure import setup_logger
from shared.protobuf import process_pb2 as pb
from shared.protobuf import process_pb2_grpc

from .errors import ProcessError
from .game.errors import GameError
from .game.manager import GameManager
from .lobby.errors import LobbyError
from .lobby.manager import LobbyManager
from .lobby.models import LobbyConfig
from .notifier import Notifier
from .pb_builders import build_game_state, build_lobby_state
from .queue.errors import QueueError
from .queue.manager import QueueManager
from .session import UserSessionIndex

logger = setup_logger(__name__)


def _status_from_error(e: ProcessError) -> pb.StatusResp:
    return pb.StatusResp(ok=False, error_code=e.code, message=e.message)


def _lobby_error_resp(e: ProcessError) -> pb.LobbyResp:
    return pb.LobbyResp(ok=False, error_code=e.code, message=e.message)


def _parse_uuid(raw: str, context: grpc.aio.ServicerContext) -> UUID | None:
    try:
        return UUID(raw)
    except (ValueError, AttributeError, TypeError):
        return None


class ProcessServiceServicer(process_pb2_grpc.ProcessServiceServicer):
    def __init__(
        self,
        lobbies: LobbyManager,
        queue: QueueManager,
        games: GameManager,
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
        user_id = _parse_uuid(request.user_id, context)
        if user_id is None:
            return pb.LobbyResp(ok=False, error_code="bad_request", message="invalid user_id")
        try:
            lobby = await self.lobbies.create(user_id)
        except LobbyError as e:
            return _lobby_error_resp(e)
        return pb.LobbyResp(ok=True, lobby_id=str(lobby.id))

    async def JoinLobby(self, request: pb.JoinReq, context) -> pb.LobbyResp:
        user_id = _parse_uuid(request.user_id, context)
        lobby_id = _parse_uuid(request.lobby_id, context)
        if user_id is None or lobby_id is None:
            return pb.LobbyResp(ok=False, error_code="bad_request", message="invalid id")
        try:
            lobby = await self.lobbies.join(lobby_id, user_id)
        except LobbyError as e:
            return _lobby_error_resp(e)
        return pb.LobbyResp(ok=True, lobby_id=str(lobby.id))

    async def LeaveLobby(self, request: pb.UserRef, context) -> pb.StatusResp:
        user_id = _parse_uuid(request.user_id, context)
        if user_id is None:
            return pb.StatusResp(ok=False, error_code="bad_request", message="invalid user_id")
        lobby = self.lobbies.get_by_user(user_id)
        if lobby is None:
            return pb.StatusResp(ok=False, error_code="user_not_in_lobby", message="user not in any lobby")
        try:
            await self.lobbies.leave(lobby.id, user_id)
        except LobbyError as e:
            return _status_from_error(e)
        return pb.StatusResp(ok=True)

    async def SeatPlayer(self, request: pb.SeatReq, context) -> pb.StatusResp:
        leader_id = _parse_uuid(request.leader_id, context)
        target_id = _parse_uuid(request.target_user_id, context)
        if leader_id is None or target_id is None:
            return pb.StatusResp(ok=False, error_code="bad_request", message="invalid id")
        lobby = self.lobbies.get_by_user(leader_id)
        if lobby is None:
            return pb.StatusResp(ok=False, error_code="user_not_in_lobby", message="leader not in lobby")
        try:
            await self.lobbies.seat(lobby.id, leader_id, target_id, request.pos)
        except LobbyError as e:
            return _status_from_error(e)
        return pb.StatusResp(ok=True)

    async def UnseatPlayer(self, request: pb.UnseatReq, context) -> pb.StatusResp:
        leader_id = _parse_uuid(request.leader_id, context)
        if leader_id is None:
            return pb.StatusResp(ok=False, error_code="bad_request", message="invalid leader_id")
        lobby = self.lobbies.get_by_user(leader_id)
        if lobby is None:
            return pb.StatusResp(ok=False, error_code="user_not_in_lobby", message="leader not in lobby")
        try:
            await self.lobbies.unseat(lobby.id, leader_id, request.pos)
        except LobbyError as e:
            return _status_from_error(e)
        return pb.StatusResp(ok=True)

    async def KickFromLobby(self, request: pb.KickReq, context) -> pb.StatusResp:
        leader_id = _parse_uuid(request.leader_id, context)
        target_id = _parse_uuid(request.target_user_id, context)
        if leader_id is None or target_id is None:
            return pb.StatusResp(ok=False, error_code="bad_request", message="invalid id")
        lobby = self.lobbies.get_by_user(leader_id)
        if lobby is None:
            return pb.StatusResp(ok=False, error_code="user_not_in_lobby", message="leader not in lobby")
        try:
            await self.lobbies.kick(lobby.id, leader_id, target_id)
        except LobbyError as e:
            return _status_from_error(e)
        return pb.StatusResp(ok=True)

    async def SetLobbyConfig(self, request: pb.SetConfigReq, context) -> pb.StatusResp:
        leader_id = _parse_uuid(request.leader_id, context)
        if leader_id is None:
            return pb.StatusResp(ok=False, error_code="bad_request", message="invalid leader_id")
        lobby = self.lobbies.get_by_user(leader_id)
        if lobby is None:
            return pb.StatusResp(ok=False, error_code="user_not_in_lobby", message="leader not in lobby")
        cfg = LobbyConfig(
            initial_ms=request.initial_ms,
            increment_ms=request.increment_ms,
            rated=request.rated,
        )
        try:
            await self.lobbies.set_config(lobby.id, leader_id, cfg)
        except LobbyError as e:
            return _status_from_error(e)
        return pb.StatusResp(ok=True)

    async def StartMatchmaking(self, request: pb.UserRef, context) -> pb.StatusResp:
        user_id = _parse_uuid(request.user_id, context)
        if user_id is None:
            return pb.StatusResp(ok=False, error_code="bad_request", message="invalid user_id")
        lobby = self.lobbies.get_by_user(user_id)
        if lobby is None:
            return pb.StatusResp(ok=False, error_code="user_not_in_lobby", message="user not in lobby")
        if lobby.leader_id != user_id:
            return pb.StatusResp(ok=False, error_code="not_leader", message="only leader can start matchmaking")
        try:
            await self.queue.enqueue(lobby)
        except (QueueError, LobbyError) as e:
            return _status_from_error(e)
        return pb.StatusResp(ok=True)

    async def CancelMatchmaking(self, request: pb.UserRef, context) -> pb.StatusResp:
        user_id = _parse_uuid(request.user_id, context)
        if user_id is None:
            return pb.StatusResp(ok=False, error_code="bad_request", message="invalid user_id")
        lobby = self.lobbies.get_by_user(user_id)
        if lobby is None:
            return pb.StatusResp(ok=False, error_code="user_not_in_lobby", message="user not in lobby")
        if lobby.leader_id != user_id:
            return pb.StatusResp(ok=False, error_code="not_leader", message="only leader can cancel matchmaking")
        try:
            await self.queue.cancel(lobby.id)
        except (QueueError, LobbyError) as e:
            return _status_from_error(e)
        # Lobby state must return to IDLE so subsequent edits are possible.
        return pb.StatusResp(ok=True)

    async def GetLobby(self, request: pb.LobbyRef, context) -> pb.LobbyStateResp:
        lobby_id = _parse_uuid(request.lobby_id, context)
        if lobby_id is None:
            return pb.LobbyStateResp(ok=False, error_code="bad_request", message="invalid lobby_id")
        lobby = self.lobbies.get(lobby_id)
        if lobby is None:
            return pb.LobbyStateResp(ok=False, error_code="lobby_not_found", message="Lobby not found")
        return pb.LobbyStateResp(ok=True, lobby=build_lobby_state(lobby))

    # ---------------- Game ----------------

    async def MakeMove(self, request: pb.MoveReq, context) -> pb.StatusResp:
        user_id = _parse_uuid(request.user_id, context)
        if user_id is None:
            return pb.StatusResp(ok=False, error_code="bad_request", message="invalid user_id")
        game = self.games.get_game_by_user(user_id)
        if game is None:
            return pb.StatusResp(ok=False, error_code="game_not_found", message="No active game for user")
        try:
            await self.games.make_move(game.id, user_id, request.uci)
        except GameError as e:
            return _status_from_error(e)
        return pb.StatusResp(ok=True)

    async def Resign(self, request: pb.UserRef, context) -> pb.StatusResp:
        user_id = _parse_uuid(request.user_id, context)
        if user_id is None:
            return pb.StatusResp(ok=False, error_code="bad_request", message="invalid user_id")
        game = self.games.get_game_by_user(user_id)
        if game is None:
            return pb.StatusResp(ok=False, error_code="game_not_found", message="No active game for user")
        try:
            await self.games.resign(game.id, user_id)
        except GameError as e:
            return _status_from_error(e)
        return pb.StatusResp(ok=True)

    async def GetGameState(self, request: pb.UserRef, context) -> pb.GameStateResp:
        user_id = _parse_uuid(request.user_id, context)
        if user_id is None:
            return pb.GameStateResp(ok=False, error_code="bad_request", message="invalid user_id")
        game = self.games.get_game_by_user(user_id)
        if game is None:
            return pb.GameStateResp(ok=False, error_code="game_not_found", message="No active game for user")
        return pb.GameStateResp(ok=True, game=build_game_state(game, user_id))

    # ---------------- Session ----------------

    async def GetUserSnapshot(self, request: pb.UserRef, context) -> pb.SnapshotResp:
        user_id = _parse_uuid(request.user_id, context)
        if user_id is None:
            return pb.SnapshotResp(ok=False, error_code="bad_request", message="invalid user_id")
        return self.sessions.get_snapshot(user_id)
