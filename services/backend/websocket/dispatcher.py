
import json
from collections.abc import Awaitable, Callable
from typing import Any

import grpc
from google.protobuf.json_format import MessageToDict
from pydantic import BaseModel, ValidationError

from shared.database import User
from shared.infrastructure import setup_logger
from shared.protobuf import process_pb2, process_pb2_grpc

logger = setup_logger(__name__)


class PingCmd(BaseModel):
    pass


class LobbyCreate(BaseModel):
    pass


class LobbyJoin(BaseModel):
    lobby_id: str


class LobbyLeave(BaseModel):
    pass


class LobbySeat(BaseModel):
    user_id: str
    pos: int


class LobbyUnseat(BaseModel):
    pos: int


class LobbyKick(BaseModel):
    user_id: str


class LobbyConfig(BaseModel):
    initial_ms: int
    increment_ms: int
    rated: bool


class QueueStart(BaseModel):
    pass


class QueueCancel(BaseModel):
    pass


class GameMove(BaseModel):
    uci: str


class GameResign(BaseModel):
    pass


Handler = Callable[
    [process_pb2_grpc.ProcessServiceStub, User, BaseModel],
    Awaitable[dict[str, Any] | None],
]


def _status_error(resp: process_pb2.StatusResp | process_pb2.LobbyResp) -> dict[str, Any] | None:
    if resp.ok:
        return None
    return {
        "type": "error",
        "code": resp.error_code or "unknown",
        "message": resp.message or "",
    }


async def _h_lobby_create(stub: process_pb2_grpc.ProcessServiceStub, user: User, _: BaseModel) -> dict[str, Any] | None:
    resp = await stub.CreateLobby(process_pb2.UserRef(user_id=str(user.id)))
    return _status_error(resp)


async def _h_lobby_join(stub: process_pb2_grpc.ProcessServiceStub, user: User, cmd: BaseModel) -> dict[str, Any] | None:
    assert isinstance(cmd, LobbyJoin)
    resp = await stub.JoinLobby(process_pb2.JoinReq(user_id=str(user.id), lobby_id=cmd.lobby_id))
    return _status_error(resp)


async def _h_lobby_leave(stub: process_pb2_grpc.ProcessServiceStub, user: User, _: BaseModel) -> dict[str, Any] | None:
    resp = await stub.LeaveLobby(process_pb2.UserRef(user_id=str(user.id)))
    return _status_error(resp)


async def _h_lobby_seat(stub: process_pb2_grpc.ProcessServiceStub, user: User, cmd: BaseModel) -> dict[str, Any] | None:
    assert isinstance(cmd, LobbySeat)
    resp = await stub.SeatPlayer(process_pb2.SeatReq(
        leader_id=str(user.id),
        target_user_id=cmd.user_id,
        pos=cmd.pos,
    ))
    return _status_error(resp)


async def _h_lobby_unseat(stub: process_pb2_grpc.ProcessServiceStub, user: User, cmd: BaseModel) -> dict[str, Any] | None:
    assert isinstance(cmd, LobbyUnseat)
    resp = await stub.UnseatPlayer(process_pb2.UnseatReq(leader_id=str(user.id), pos=cmd.pos))
    return _status_error(resp)


async def _h_lobby_kick(stub: process_pb2_grpc.ProcessServiceStub, user: User, cmd: BaseModel) -> dict[str, Any] | None:
    assert isinstance(cmd, LobbyKick)
    resp = await stub.KickFromLobby(process_pb2.KickReq(
        leader_id=str(user.id),
        target_user_id=cmd.user_id,
    ))
    return _status_error(resp)


async def _h_lobby_config(stub: process_pb2_grpc.ProcessServiceStub, user: User, cmd: BaseModel) -> dict[str, Any] | None:
    assert isinstance(cmd, LobbyConfig)
    resp = await stub.SetLobbyConfig(process_pb2.SetConfigReq(
        leader_id=str(user.id),
        initial_ms=cmd.initial_ms,
        increment_ms=cmd.increment_ms,
        rated=cmd.rated,
    ))
    return _status_error(resp)


async def _h_queue_start(stub: process_pb2_grpc.ProcessServiceStub, user: User, _: BaseModel) -> dict[str, Any] | None:
    resp = await stub.StartMatchmaking(process_pb2.UserRef(user_id=str(user.id)))
    return _status_error(resp)


async def _h_queue_cancel(stub: process_pb2_grpc.ProcessServiceStub, user: User, _: BaseModel) -> dict[str, Any] | None:
    resp = await stub.CancelMatchmaking(process_pb2.UserRef(user_id=str(user.id)))
    return _status_error(resp)


async def _h_game_move(stub: process_pb2_grpc.ProcessServiceStub, user: User, cmd: BaseModel) -> dict[str, Any] | None:
    assert isinstance(cmd, GameMove)
    resp = await stub.MakeMove(process_pb2.MoveReq(user_id=str(user.id), uci=cmd.uci))
    return _status_error(resp)


async def _h_game_resign(stub: process_pb2_grpc.ProcessServiceStub, user: User, _: BaseModel) -> dict[str, Any] | None:
    resp = await stub.Resign(process_pb2.UserRef(user_id=str(user.id)))
    return _status_error(resp)


COMMANDS: dict[str, tuple[type[BaseModel], Handler]] = {
    "lobby.create":  (LobbyCreate, _h_lobby_create),
    "lobby.join":    (LobbyJoin, _h_lobby_join),
    "lobby.leave":   (LobbyLeave, _h_lobby_leave),
    "lobby.seat":    (LobbySeat, _h_lobby_seat),
    "lobby.unseat":  (LobbyUnseat, _h_lobby_unseat),
    "lobby.kick":    (LobbyKick, _h_lobby_kick),
    "lobby.config":  (LobbyConfig, _h_lobby_config),
    "queue.start":   (QueueStart, _h_queue_start),
    "queue.cancel":  (QueueCancel, _h_queue_cancel),
    "game.move":     (GameMove, _h_game_move),
    "game.resign":   (GameResign, _h_game_resign),
}


async def dispatch(
    stub: process_pb2_grpc.ProcessServiceStub,
    user: User,
    raw: str,
) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"type": "error", "code": "bad_request", "message": "invalid json"}

    if not isinstance(payload, dict):
        return {"type": "error", "code": "bad_request", "message": "payload must be an object"}

    msg_type = payload.get("type")
    if not isinstance(msg_type, str):
        return {"type": "error", "code": "bad_request", "message": "missing 'type'"}

    if msg_type == "ping":
        return {"type": "pong"}

    entry = COMMANDS.get(msg_type)
    if entry is None:
        return {"type": "error", "code": "bad_request", "message": f"unknown type: {msg_type}"}

    model_cls, handler = entry
    body = {k: v for k, v in payload.items() if k != "type"}
    try:
        cmd = model_cls.model_validate(body)
    except ValidationError as exc:
        return {"type": "error", "code": "bad_request", "message": exc.errors(include_url=False).__repr__()}

    try:
        return await handler(stub, user, cmd)
    except grpc.aio.AioRpcError as exc:
        logger.warning("grpc error on %s: %s", msg_type, exc)
        return {
            "type": "error",
            "code": exc.code().name if exc.code() is not None else "grpc_error",
            "message": exc.details() or "",
        }


def snapshot_to_json(resp: process_pb2.SnapshotResp) -> str:
    if not resp.ok:
        return json.dumps({
            "type": "error",
            "code": resp.error_code or "snapshot_failed",
            "message": resp.message or "",
        }, ensure_ascii=False)
    body: dict[str, Any] = {"type": "snapshot", "state": resp.state}
    if resp.HasField("lobby"):
        body["lobby"] = MessageToDict(resp.lobby, preserving_proto_field_name=True)
    if resp.HasField("game"):
        body["game"] = MessageToDict(resp.game, preserving_proto_field_name=True)
    return json.dumps(body, ensure_ascii=False)
