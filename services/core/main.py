from __future__ import annotations

from shared.events import SyncData
from shared.infrastructure import setup_logger
from shared.protobuf import core_pb2 as pb
from shared.protobuf import core_pb2_grpc

from .errors import coreError
from .game.errors import GameError
from .game.manager import GameManager
from .invites import InviteManager
from .lobby.errors import LobbyError
from .lobby.manager import LobbyManager
from .lobby.models import LobbyConfig
from .notifier import Notifier
from .queue.errors import QueueError
from .queue.manager import QueueManager
from .session import UserSessionIndex

logger = setup_logger(__name__)


def _ok() -> pb.StatusResp:
    return pb.StatusResp(ok=True)


def _err(e: coreError) -> pb.StatusResp:
    return pb.StatusResp(ok=False, error_code=e.code, message=e.message)


def _err_raw(code: str, message: str = "") -> pb.StatusResp:
    return pb.StatusResp(ok=False, error_code=code, message=message)


class CoreServiceServicer(core_pb2_grpc.CoreServiceServicer):
    def __init__(
        self,
        lobbies: LobbyManager,
        queue: QueueManager,
        games: GameManager,
        invites: InviteManager,
        notifier: Notifier,
        sessions: UserSessionIndex,
    ) -> None:
        self.lobbies = lobbies
        self.queue = queue
        self.games = games
        self.invites = invites
        self.notifier = notifier
        self.sessions = sessions

    # ---------------- Lobby ----------------

    async def CreateLobby(self, request: pb.CreateLobbyReq, context) -> pb.StatusResp:
        username = request.username
        logger.debug(
            "CreateLobby request: username=%s init=%s incr=%s",
            username, request.initial_ms, request.increment_ms,
        )
        if not username:
            return _err_raw("bad_request", "missing username")
        cfg = LobbyConfig(
            initial_ms=request.initial_ms or 180_000,
            increment_ms=request.increment_ms or 0,
            rated=False,
        )
        try:
            await self.lobbies.create(username, cfg)
        except LobbyError as e:
            logger.warning("CreateLobby error: %s/%s", e.code, e.message)
            return _err(e)
        return _ok()

    async def LeaveLobby(self, request: pb.UserRef, context) -> pb.StatusResp:
        username = request.username
        logger.debug("LeaveLobby request: username=%s", username)
        if not username:
            return _err_raw("bad_request", "missing username")
        try:
            await self.lobbies.leave(username)
        except LobbyError as e:
            logger.warning("LeaveLobby error: %s/%s", e.code, e.message)
            return _err(e)
        # any pending invites for or from this user are stale
        self.invites.cleanup_for_user(username)
        return _ok()

    async def KickFromLobby(self, request: pb.KickReq, context) -> pb.StatusResp:
        leader, target = request.leader, request.target
        logger.debug("KickFromLobby request: leader=%s target=%s", leader, target)
        if not leader or not target:
            return _err_raw("bad_request", "missing leader/target")
        try:
            await self.lobbies.kick(leader, target)
        except LobbyError as e:
            logger.warning("KickFromLobby error: %s/%s", e.code, e.message)
            return _err(e)
        self.invites.cleanup_for_user(target)
        return _ok()

    async def SetLobbyConfig(self, request: pb.SetConfigReq, context) -> pb.StatusResp:
        leader = request.leader
        logger.debug(
            "SetLobbyConfig request: leader=%s init=%s incr=%s rated=%s",
            leader, request.initial_ms, request.increment_ms, request.rated,
        )
        if not leader:
            return _err_raw("bad_request", "missing leader")
        cfg = LobbyConfig(
            initial_ms=request.initial_ms,
            increment_ms=request.increment_ms,
            rated=request.rated,
        )
        try:
            await self.lobbies.set_config(leader, cfg)
        except LobbyError as e:
            logger.warning("SetLobbyConfig error: %s/%s", e.code, e.message)
            return _err(e)
        return _ok()

    async def StartMatchmaking(self, request: pb.UserRef, context) -> pb.StatusResp:
        username = request.username
        logger.debug("StartMatchmaking request: username=%s", username)
        if not username:
            return _err_raw("bad_request", "missing username")
        lobby = self.lobbies.get_by_user(username)
        if lobby is None:
            return _err_raw("user_not_in_lobby", "user not in lobby")
        if lobby.leader != username:
            return _err_raw("not_leader", "only leader can start matchmaking")
        try:
            await self.queue.enqueue(lobby)
        except (QueueError, LobbyError) as e:
            logger.warning("StartMatchmaking error: %s/%s", e.code, e.message)
            return _err(e)
        # invites become irrelevant once we're queued
        self.invites.cleanup_for_lobby(lobby.id)
        return _ok()

    async def CancelMatchmaking(self, request: pb.UserRef, context) -> pb.StatusResp:
        username = request.username
        logger.debug("CancelMatchmaking request: username=%s", username)
        if not username:
            return _err_raw("bad_request", "missing username")
        lobby = self.lobbies.get_by_user(username)
        if lobby is None:
            return _err_raw("user_not_in_lobby", "user not in lobby")
        if lobby.leader != username:
            return _err_raw("not_leader", "only leader can cancel matchmaking")
        try:
            await self.queue.cancel(lobby.id)
        except (QueueError, LobbyError) as e:
            logger.warning("CancelMatchmaking error: %s/%s", e.code, e.message)
            return _err(e)
        return _ok()

    # ---------------- Invites ----------------

    async def SendInvite(self, request: pb.SendInviteReq, context) -> pb.StatusResp:
        sender, receiver, idx = request.sender, request.receiver, request.idx
        logger.debug(
            "SendInvite request: sender=%s receiver=%s idx=%s",
            sender, receiver, idx,
        )
        if not sender or not receiver:
            return _err_raw("bad_request", "missing sender/receiver")
        try:
            await self.invites.send(sender, receiver, idx)
        except LobbyError as e:
            logger.warning("SendInvite error: %s/%s", e.code, e.message)
            return _err(e)
        return _ok()

    async def AcceptInvite(self, request: pb.AcceptInviteReq, context) -> pb.StatusResp:
        receiver, sender = request.receiver, request.sender
        logger.debug("AcceptInvite request: receiver=%s sender=%s", receiver, sender)
        if not sender or not receiver:
            return _err_raw("bad_request", "missing sender/receiver")
        try:
            await self.invites.accept(receiver, sender)
        except LobbyError as e:
            logger.warning("AcceptInvite error: %s/%s", e.code, e.message)
            return _err(e)
        return _ok()

    async def RejectInvite(self, request: pb.RejectInviteReq, context) -> pb.StatusResp:
        receiver, sender = request.receiver, request.sender
        logger.debug("RejectInvite request: receiver=%s sender=%s", receiver, sender)
        if not sender or not receiver:
            return _err_raw("bad_request", "missing sender/receiver")
        try:
            await self.invites.reject(receiver, sender)
        except LobbyError as e:
            logger.warning("RejectInvite error: %s/%s", e.code, e.message)
            return _err(e)
        return _ok()

    # ---------------- Game ----------------

    async def MakeMove(self, request: pb.MoveReq, context) -> pb.StatusResp:
        username = request.username
        logger.debug("MakeMove request: username=%s uci=%s", username, request.uci)
        if not username:
            return _err_raw("bad_request", "missing username")
        try:
            await self.games.make_move(username, request.uci)
        except GameError as e:
            logger.warning("MakeMove error: %s/%s", e.code, e.message)
            return _err(e)
        return _ok()

    async def Resign(self, request: pb.UserRef, context) -> pb.StatusResp:
        username = request.username
        logger.debug("Resign request: username=%s", username)
        if not username:
            return _err_raw("bad_request", "missing username")
        try:
            await self.games.resign(username)
        except GameError as e:
            logger.warning("Resign error: %s/%s", e.code, e.message)
            return _err(e)
        return _ok()

    async def SendChat(self, request: pb.ChatReq, context) -> pb.StatusResp:
        # Game chat is currently disabled in backend.
        return _err_raw("not_implemented", "game chat is not implemented")

    # ---------------- Sync ----------------

    async def GetUserSnapshot(self, request: pb.UserRef, context) -> pb.SnapshotResp:
        username = request.username
        logger.debug("GetUserSnapshot request: username=%s", username)
        if not username:
            return pb.SnapshotResp(ok=False, error_code="bad_request", message="missing username")
        sync = self.sessions.get_sync(username)
        return pb.SnapshotResp(ok=True, sync_json=_dump_sync(sync))


def _dump_sync(sync: SyncData) -> str:
    return sync.model_dump_json(by_alias=True)
