from __future__ import annotations

from uuid import UUID

import grpc

from shared.infrastructure import setup_logger
from shared.protobuf import core_pb2 as pb
from shared.protobuf import core_pb2_grpc

from .errors import coreError
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


def _status_from_error(e: coreError) -> pb.StatusResp:
    return pb.StatusResp(ok=False, error_code=e.code, message=e.message)


def _lobby_error_resp(e: coreError) -> pb.LobbyResp:
    return pb.LobbyResp(ok=False, error_code=e.code, message=e.message)


def _parse_uuid(raw: str, context: grpc.aio.ServicerContext) -> UUID | None:
    try:
        return UUID(raw)
    except (ValueError, AttributeError, TypeError):
        return None


class CoreServiceServicer(core_pb2_grpc.CoreServiceServicer):
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
        logger.debug("CreateLobby request: user_id=%s", request.user_id)
        user_id = _parse_uuid(request.user_id, context)
        if user_id is None:
            logger.debug("CreateLobby response: ok=False error_code=bad_request")
            return pb.LobbyResp(ok=False, error_code="bad_request", message="invalid user_id")
        try:
            lobby = await self.lobbies.create(user_id)
        except LobbyError as e:
            logger.warning("CreateLobby error: user_id=%s error=%s message=%s", user_id, e.code, e.message)
            return _lobby_error_resp(e)
        logger.debug("CreateLobby response: ok=True lobby_id=%s", lobby.id)
        return pb.LobbyResp(ok=True, lobby_id=str(lobby.id))

    async def JoinLobby(self, request: pb.JoinReq, context) -> pb.LobbyResp:
        logger.debug("JoinLobby request: user_id=%s lobby_id=%s", request.user_id, request.lobby_id)
        user_id = _parse_uuid(request.user_id, context)
        lobby_id = _parse_uuid(request.lobby_id, context)
        if user_id is None or lobby_id is None:
            logger.debug("JoinLobby response: ok=False error_code=bad_request")
            return pb.LobbyResp(ok=False, error_code="bad_request", message="invalid id")
        try:
            lobby = await self.lobbies.join(lobby_id, user_id)
        except LobbyError as e:
            logger.warning("JoinLobby error: user_id=%s lobby_id=%s error=%s message=%s", user_id, lobby_id, e.code, e.message)
            return _lobby_error_resp(e)
        logger.debug("JoinLobby response: ok=True lobby_id=%s", lobby.id)
        return pb.LobbyResp(ok=True, lobby_id=str(lobby.id))

    async def LeaveLobby(self, request: pb.UserRef, context) -> pb.StatusResp:
        logger.debug("LeaveLobby request: user_id=%s", request.user_id)
        user_id = _parse_uuid(request.user_id, context)
        if user_id is None:
            logger.debug("LeaveLobby response: ok=False error_code=bad_request")
            return pb.StatusResp(ok=False, error_code="bad_request", message="invalid user_id")
        lobby = self.lobbies.get_by_user(user_id)
        if lobby is None:
            logger.debug("LeaveLobby response: ok=False error_code=user_not_in_lobby user_id=%s", user_id)
            return pb.StatusResp(ok=False, error_code="user_not_in_lobby", message="user not in any lobby")
        try:
            await self.lobbies.leave(lobby.id, user_id)
        except LobbyError as e:
            logger.warning("LeaveLobby error: user_id=%s lobby_id=%s error=%s message=%s", user_id, lobby.id, e.code, e.message)
            return _status_from_error(e)
        logger.debug("LeaveLobby response: ok=True user_id=%s lobby_id=%s", user_id, lobby.id)
        return pb.StatusResp(ok=True)

    async def SeatPlayer(self, request: pb.SeatReq, context) -> pb.StatusResp:
        logger.debug("SeatPlayer request: leader_id=%s target_user_id=%s pos=%s", request.leader_id, request.target_user_id, request.pos)
        leader_id = _parse_uuid(request.leader_id, context)
        target_id = _parse_uuid(request.target_user_id, context)
        if leader_id is None or target_id is None:
            logger.debug("SeatPlayer response: ok=False error_code=bad_request")
            return pb.StatusResp(ok=False, error_code="bad_request", message="invalid id")
        lobby = self.lobbies.get_by_user(leader_id)
        if lobby is None:
            logger.debug("SeatPlayer response: ok=False error_code=user_not_in_lobby leader_id=%s", leader_id)
            return pb.StatusResp(ok=False, error_code="user_not_in_lobby", message="leader not in lobby")
        try:
            await self.lobbies.seat(lobby.id, leader_id, target_id, request.pos)
        except LobbyError as e:
            logger.warning("SeatPlayer error: leader_id=%s target_id=%s lobby_id=%s pos=%s error=%s message=%s", leader_id, target_id, lobby.id, request.pos, e.code, e.message)
            return _status_from_error(e)
        logger.debug("SeatPlayer response: ok=True lobby_id=%s target_id=%s pos=%s", lobby.id, target_id, request.pos)
        return pb.StatusResp(ok=True)

    async def UnseatPlayer(self, request: pb.UnseatReq, context) -> pb.StatusResp:
        logger.debug("UnseatPlayer request: leader_id=%s pos=%s", request.leader_id, request.pos)
        leader_id = _parse_uuid(request.leader_id, context)
        if leader_id is None:
            logger.debug("UnseatPlayer response: ok=False error_code=bad_request")
            return pb.StatusResp(ok=False, error_code="bad_request", message="invalid leader_id")
        lobby = self.lobbies.get_by_user(leader_id)
        if lobby is None:
            logger.debug("UnseatPlayer response: ok=False error_code=user_not_in_lobby leader_id=%s", leader_id)
            return pb.StatusResp(ok=False, error_code="user_not_in_lobby", message="leader not in lobby")
        try:
            await self.lobbies.unseat(lobby.id, leader_id, request.pos)
        except LobbyError as e:
            logger.warning("UnseatPlayer error: leader_id=%s lobby_id=%s pos=%s error=%s message=%s", leader_id, lobby.id, request.pos, e.code, e.message)
            return _status_from_error(e)
        logger.debug("UnseatPlayer response: ok=True lobby_id=%s pos=%s", lobby.id, request.pos)
        return pb.StatusResp(ok=True)

    async def KickFromLobby(self, request: pb.KickReq, context) -> pb.StatusResp:
        logger.debug("KickFromLobby request: leader_id=%s target_user_id=%s", request.leader_id, request.target_user_id)
        leader_id = _parse_uuid(request.leader_id, context)
        target_id = _parse_uuid(request.target_user_id, context)
        if leader_id is None or target_id is None:
            logger.debug("KickFromLobby response: ok=False error_code=bad_request")
            return pb.StatusResp(ok=False, error_code="bad_request", message="invalid id")
        lobby = self.lobbies.get_by_user(leader_id)
        if lobby is None:
            logger.debug("KickFromLobby response: ok=False error_code=user_not_in_lobby leader_id=%s", leader_id)
            return pb.StatusResp(ok=False, error_code="user_not_in_lobby", message="leader not in lobby")
        try:
            await self.lobbies.kick(lobby.id, leader_id, target_id)
        except LobbyError as e:
            logger.warning("KickFromLobby error: leader_id=%s target_id=%s lobby_id=%s error=%s message=%s", leader_id, target_id, lobby.id, e.code, e.message)
            return _status_from_error(e)
        logger.debug("KickFromLobby response: ok=True lobby_id=%s target_id=%s", lobby.id, target_id)
        return pb.StatusResp(ok=True)

    async def SetLobbyConfig(self, request: pb.SetConfigReq, context) -> pb.StatusResp:
        logger.debug("SetLobbyConfig request: leader_id=%s initial_ms=%s increment_ms=%s rated=%s", request.leader_id, request.initial_ms, request.increment_ms, request.rated)
        leader_id = _parse_uuid(request.leader_id, context)
        if leader_id is None:
            logger.debug("SetLobbyConfig response: ok=False error_code=bad_request")
            return pb.StatusResp(ok=False, error_code="bad_request", message="invalid leader_id")
        lobby = self.lobbies.get_by_user(leader_id)
        if lobby is None:
            logger.debug("SetLobbyConfig response: ok=False error_code=user_not_in_lobby leader_id=%s", leader_id)
            return pb.StatusResp(ok=False, error_code="user_not_in_lobby", message="leader not in lobby")
        cfg = LobbyConfig(
            initial_ms=request.initial_ms,
            increment_ms=request.increment_ms,
            rated=request.rated,
        )
        try:
            await self.lobbies.set_config(lobby.id, leader_id, cfg)
        except LobbyError as e:
            logger.warning("SetLobbyConfig error: leader_id=%s lobby_id=%s error=%s message=%s", leader_id, lobby.id, e.code, e.message)
            return _status_from_error(e)
        logger.debug("SetLobbyConfig response: ok=True lobby_id=%s", lobby.id)
        return pb.StatusResp(ok=True)

    async def StartMatchmaking(self, request: pb.UserRef, context) -> pb.StatusResp:
        logger.debug("StartMatchmaking request: user_id=%s", request.user_id)
        user_id = _parse_uuid(request.user_id, context)
        if user_id is None:
            logger.debug("StartMatchmaking response: ok=False error_code=bad_request")
            return pb.StatusResp(ok=False, error_code="bad_request", message="invalid user_id")
        lobby = self.lobbies.get_by_user(user_id)
        if lobby is None:
            logger.debug("StartMatchmaking response: ok=False error_code=user_not_in_lobby user_id=%s", user_id)
            return pb.StatusResp(ok=False, error_code="user_not_in_lobby", message="user not in lobby")
        if lobby.leader_id != user_id:
            logger.debug("StartMatchmaking response: ok=False error_code=not_leader user_id=%s lobby_id=%s", user_id, lobby.id)
            return pb.StatusResp(ok=False, error_code="not_leader", message="only leader can start matchmaking")
        try:
            await self.queue.enqueue(lobby)
        except (QueueError, LobbyError) as e:
            logger.warning("StartMatchmaking error: user_id=%s lobby_id=%s error=%s message=%s", user_id, lobby.id, e.code, e.message)
            return _status_from_error(e)
        logger.debug("StartMatchmaking response: ok=True lobby_id=%s", lobby.id)
        return pb.StatusResp(ok=True)

    async def CancelMatchmaking(self, request: pb.UserRef, context) -> pb.StatusResp:
        logger.debug("CancelMatchmaking request: user_id=%s", request.user_id)
        user_id = _parse_uuid(request.user_id, context)
        if user_id is None:
            logger.debug("CancelMatchmaking response: ok=False error_code=bad_request")
            return pb.StatusResp(ok=False, error_code="bad_request", message="invalid user_id")
        lobby = self.lobbies.get_by_user(user_id)
        if lobby is None:
            logger.debug("CancelMatchmaking response: ok=False error_code=user_not_in_lobby user_id=%s", user_id)
            return pb.StatusResp(ok=False, error_code="user_not_in_lobby", message="user not in lobby")
        if lobby.leader_id != user_id:
            logger.debug("CancelMatchmaking response: ok=False error_code=not_leader user_id=%s lobby_id=%s", user_id, lobby.id)
            return pb.StatusResp(ok=False, error_code="not_leader", message="only leader can cancel matchmaking")
        try:
            await self.queue.cancel(lobby.id)
        except (QueueError, LobbyError) as e:
            logger.warning("CancelMatchmaking error: user_id=%s lobby_id=%s error=%s message=%s", user_id, lobby.id, e.code, e.message)
            return _status_from_error(e)
        logger.debug("CancelMatchmaking response: ok=True lobby_id=%s", lobby.id)
        # Lobby state must return to IDLE so subsequent edits are possible.
        return pb.StatusResp(ok=True)

    async def GetLobby(self, request: pb.LobbyRef, context) -> pb.LobbyStateResp:
        logger.debug("GetLobby request: lobby_id=%s", request.lobby_id)
        lobby_id = _parse_uuid(request.lobby_id, context)
        if lobby_id is None:
            logger.debug("GetLobby response: ok=False error_code=bad_request")
            return pb.LobbyStateResp(ok=False, error_code="bad_request", message="invalid lobby_id")
        lobby = self.lobbies.get(lobby_id)
        if lobby is None:
            logger.debug("GetLobby response: ok=False error_code=lobby_not_found lobby_id=%s", lobby_id)
            return pb.LobbyStateResp(ok=False, error_code="lobby_not_found", message="Lobby not found")
        logger.debug("GetLobby response: ok=True lobby_id=%s state=%s", lobby.id, lobby.state)
        return pb.LobbyStateResp(ok=True, lobby=build_lobby_state(lobby))

    # ---------------- Game ----------------

    async def MakeMove(self, request: pb.MoveReq, context) -> pb.StatusResp:
        logger.debug("MakeMove request: user_id=%s uci=%s", request.user_id, request.uci)
        user_id = _parse_uuid(request.user_id, context)
        if user_id is None:
            logger.debug("MakeMove response: ok=False error_code=bad_request")
            return pb.StatusResp(ok=False, error_code="bad_request", message="invalid user_id")
        game = self.games.get_game_by_user(user_id)
        if game is None:
            logger.debug("MakeMove response: ok=False error_code=game_not_found user_id=%s", user_id)
            return pb.StatusResp(ok=False, error_code="game_not_found", message="No active game for user")
        try:
            await self.games.make_move(game.id, user_id, request.uci)
        except GameError as e:
            logger.warning("MakeMove error: user_id=%s game_id=%s uci=%s error=%s message=%s", user_id, game.id, request.uci, e.code, e.message)
            return _status_from_error(e)
        logger.debug("MakeMove response: ok=True game_id=%s uci=%s", game.id, request.uci)
        return pb.StatusResp(ok=True)

    async def Resign(self, request: pb.UserRef, context) -> pb.StatusResp:
        logger.debug("Resign request: user_id=%s", request.user_id)
        user_id = _parse_uuid(request.user_id, context)
        if user_id is None:
            logger.debug("Resign response: ok=False error_code=bad_request")
            return pb.StatusResp(ok=False, error_code="bad_request", message="invalid user_id")
        game = self.games.get_game_by_user(user_id)
        if game is None:
            logger.debug("Resign response: ok=False error_code=game_not_found user_id=%s", user_id)
            return pb.StatusResp(ok=False, error_code="game_not_found", message="No active game for user")
        try:
            await self.games.resign(game.id, user_id)
        except GameError as e:
            logger.warning("Resign error: user_id=%s game_id=%s error=%s message=%s", user_id, game.id, e.code, e.message)
            return _status_from_error(e)
        logger.debug("Resign response: ok=True user_id=%s game_id=%s", user_id, game.id)
        return pb.StatusResp(ok=True)

    async def GetGameState(self, request: pb.UserRef, context) -> pb.GameStateResp:
        logger.debug("GetGameState request: user_id=%s", request.user_id)
        user_id = _parse_uuid(request.user_id, context)
        if user_id is None:
            logger.debug("GetGameState response: ok=False error_code=bad_request")
            return pb.GameStateResp(ok=False, error_code="bad_request", message="invalid user_id")
        game = self.games.get_game_by_user(user_id)
        if game is None:
            logger.debug("GetGameState response: ok=False error_code=game_not_found user_id=%s", user_id)
            return pb.GameStateResp(ok=False, error_code="game_not_found", message="No active game for user")
        logger.debug("GetGameState response: ok=True user_id=%s game_id=%s", user_id, game.id)
        return pb.GameStateResp(ok=True, game=build_game_state(game, user_id))

    # ---------------- Session ----------------

    async def GetUserSnapshot(self, request: pb.UserRef, context) -> pb.SnapshotResp:
        logger.debug("GetUserSnapshot request: user_id=%s", request.user_id)
        user_id = _parse_uuid(request.user_id, context)
        if user_id is None:
            logger.debug("GetUserSnapshot response: ok=False error_code=bad_request")
            return pb.SnapshotResp(ok=False, error_code="bad_request", message="invalid user_id")
        resp = self.sessions.get_snapshot(user_id)
        logger.debug("GetUserSnapshot response: ok=%s user_id=%s", resp.ok, user_id)
        return resp
