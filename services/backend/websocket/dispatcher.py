from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import grpc
from pydantic import ValidationError

from shared.database import User
from shared.events import (
    CamelModel,
    CancelMMMsg,
    ClientMsg,
    ClientMsgAdapter,
    ErrorData,
    ErrorMsg,
    GameChatSendMsg,
    GameMoveMsg,
    GameResignMsg,
    InviteAcceptMsg,
    InviteRejectMsg,
    InviteSendMsg,
    LobbyConfigMsg,
    LobbyCreateMsg,
    LobbyKickMsg,
    LobbyLeaveMsg,
    PingMsg,
    PongMsg,
    ReqSyncMsg,
    StartMMMsg,
    SyncData,
    SyncMsg,
    WsMsgType,
)
from shared.infrastructure import setup_logger
from shared.protobuf import core_pb2 as pb

from .grpc_client import AsyncCoreServiceStub

logger = setup_logger(__name__)

Stub = AsyncCoreServiceStub
Handler = Callable[[Stub, User, Any], Awaitable[CamelModel | None]]


def _err_from_status(resp: pb.StatusResp) -> CamelModel | None:
    if resp.ok:
        return None
    return ErrorMsg(
        data=ErrorData(code=resp.error_code or "unknown", message=resp.message or "")
    )


def _err_from_grpc(exc: grpc.aio.AioRpcError) -> ErrorMsg:
    code = exc.code().name if exc.code() is not None else "grpc_error"
    return ErrorMsg(data=ErrorData(code=code, message=exc.details() or ""))


# ---------------- Handlers ----------------

async def _h_ping(stub: Stub, user: User, _: PingMsg) -> CamelModel:
    return PongMsg()


async def _h_req_sync(stub: Stub, user: User, _: ReqSyncMsg) -> CamelModel:
    resp: pb.SnapshotResp = await stub.GetUserSnapshot(
        pb.UserRef(username=user.username)
    )
    if not resp.ok:
        return ErrorMsg(
            data=ErrorData(
                code=resp.error_code or "snapshot_failed",
                message=resp.message or "",
            )
        )
    sync = SyncData.model_validate_json(resp.sync_json)
    return SyncMsg(data=sync)


async def _h_lobby_create(stub: Stub, user: User, cmd: LobbyCreateMsg) -> CamelModel | None:
    resp = await stub.CreateLobby(
        pb.CreateLobbyReq(
            username=user.username,
            clock_time=cmd.data.clock_time,
            incr=cmd.data.incr,
        )
    )
    return _err_from_status(resp)


async def _h_lobby_leave(stub: Stub, user: User, _: LobbyLeaveMsg) -> CamelModel | None:
    resp = await stub.LeaveLobby(pb.UserRef(username=user.username))
    return _err_from_status(resp)


async def _h_lobby_kick(stub: Stub, user: User, cmd: LobbyKickMsg) -> CamelModel | None:
    resp = await stub.KickFromLobby(
        pb.KickReq(leader=user.username, target=cmd.data)
    )
    return _err_from_status(resp)


async def _h_invite_send(stub: Stub, user: User, cmd: InviteSendMsg) -> CamelModel | None:
    resp = await stub.SendInvite(
        pb.SendInviteReq(
            sender=user.username,
            receiver=cmd.data.username,
            idx=cmd.data.idx,
        )
    )
    return _err_from_status(resp)


async def _h_invite_accept(stub: Stub, user: User, cmd: InviteAcceptMsg) -> CamelModel | None:
    resp = await stub.AcceptInvite(
        pb.AcceptInviteReq(receiver=user.username, sender=cmd.data)
    )
    return _err_from_status(resp)


async def _h_invite_reject(stub: Stub, user: User, cmd: InviteRejectMsg) -> CamelModel | None:
    resp = await stub.RejectInvite(
        pb.RejectInviteReq(receiver=user.username, sender=cmd.data)
    )
    return _err_from_status(resp)


async def _h_lobby_config(stub: Stub, user: User, cmd: LobbyConfigMsg) -> CamelModel | None:
    resp = await stub.SetLobbyConfig(
        pb.SetConfigReq(
            leader=user.username,
            clock_time=cmd.data.clock_time,
            incr=cmd.data.incr,
            rated=cmd.data.rated,
        )
    )
    return _err_from_status(resp)


async def _h_start_mm(stub: Stub, user: User, _: StartMMMsg) -> CamelModel | None:
    resp = await stub.StartMatchmaking(pb.UserRef(username=user.username))
    return _err_from_status(resp)


async def _h_cancel_mm(stub: Stub, user: User, _: CancelMMMsg) -> CamelModel | None:
    resp = await stub.CancelMatchmaking(pb.UserRef(username=user.username))
    return _err_from_status(resp)


async def _h_game_move(stub: Stub, user: User, cmd: GameMoveMsg) -> CamelModel | None:
    resp = await stub.MakeMove(
        pb.MoveReq(username=user.username, uci=cmd.data.move)
    )
    return _err_from_status(resp)


async def _h_game_chat(stub: Stub, user: User, cmd: GameChatSendMsg) -> CamelModel | None:
    resp = await stub.SendChat(pb.ChatReq(username=user.username, text=cmd.data))
    return _err_from_status(resp)


async def _h_game_resign(stub: Stub, user: User, _: GameResignMsg) -> CamelModel | None:
    resp = await stub.Resign(pb.UserRef(username=user.username))
    return _err_from_status(resp)


HANDLERS: dict[int, Handler] = {
    WsMsgType.PING.value:               _h_ping,
    WsMsgType.REQ_SYNC.value:           _h_req_sync,
    WsMsgType.LOBBY_CREATE.value:       _h_lobby_create,
    WsMsgType.LOBBY_LEAVE.value:        _h_lobby_leave,
    WsMsgType.LOBBY_KICK.value:         _h_lobby_kick,
    WsMsgType.INVITE_SEND.value:        _h_invite_send,
    WsMsgType.INVITE_ACCEPT.value:      _h_invite_accept,
    WsMsgType.INVITE_REJECT.value:      _h_invite_reject,
    WsMsgType.LOBBY_CONFIG.value:       _h_lobby_config,
    WsMsgType.START_MM.value:           _h_start_mm,
    WsMsgType.CANCEL_MM.value:          _h_cancel_mm,
    WsMsgType.GAME_MOVE.value:          _h_game_move,
    WsMsgType.GAME_CHAT_MSG_SEND.value: _h_game_chat,
    WsMsgType.GAME_RESIGN.value:        _h_game_resign,
}


async def dispatch(stub: Stub, user: User, raw: str) -> CamelModel | None:
    try:
        cmd: ClientMsg = ClientMsgAdapter.validate_json(raw)
    except ValidationError as exc:
        return ErrorMsg(
            data=ErrorData(
                code="bad_request",
                message=json.dumps(
                    exc.errors(include_url=False), ensure_ascii=False
                ),
            )
        )
    except ValueError:
        return ErrorMsg(data=ErrorData(code="bad_request", message="invalid json"))

    handler = HANDLERS.get(cmd.type)
    if handler is None:
        return ErrorMsg(
            data=ErrorData(code="unknown_type", message=f"no handler for type={cmd.type}")
        )
    try:
        return await handler(stub, user, cmd)
    except grpc.aio.AioRpcError as exc:
        logger.warning("grpc error on type=%s: %s", cmd.type, exc)
        return _err_from_grpc(exc)
