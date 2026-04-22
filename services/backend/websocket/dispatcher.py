
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import grpc
from pydantic import ValidationError

from shared.database import User
from shared.events import (
    ClientEvent,
    ClientEventAdapter,
    ErrorEvent,
    GameMove,
    GameStatePayload,
    LobbyConfig,
    LobbyJoin,
    LobbyKick,
    LobbyPayload,
    LobbySeat,
    LobbyUnseat,
    PocketsPayload,
    ServerEvent,
    SnapshotEvent,
)
from shared.events.common import SnapshotStateStr
from shared.infrastructure import setup_logger
from shared.protobuf import process_pb2, process_pb2_grpc

logger = setup_logger(__name__)


Handler = Callable[
    [process_pb2_grpc.ProcessServiceStub, User, Any],
    Awaitable[ServerEvent | None],
]


def _status_error(
    resp: process_pb2.StatusResp | process_pb2.LobbyResp,
) -> ServerEvent | None:
    if resp.ok:
        return None
    return ErrorEvent(code=resp.error_code or "unknown", message=resp.message or "")


def _grpc_error(exc: grpc.aio.AioRpcError) -> ErrorEvent:
    code = exc.code().name if exc.code() is not None else "grpc_error"
    return ErrorEvent(code=code, message=exc.details() or "")


async def _h_ping(stub: Any, user: User, _: Any) -> ServerEvent:
    from shared.events import Pong
    return Pong()


async def _h_lobby_create(stub: Any, user: User, _: Any) -> ServerEvent | None:
    resp = await stub.CreateLobby(process_pb2.UserRef(user_id=str(user.id)))
    return _status_error(resp)


async def _h_lobby_join(stub: Any, user: User, cmd: LobbyJoin) -> ServerEvent | None:
    resp = await stub.JoinLobby(
        process_pb2.JoinReq(user_id=str(user.id), lobby_id=cmd.lobby_id)
    )
    return _status_error(resp)


async def _h_lobby_leave(stub: Any, user: User, _: Any) -> ServerEvent | None:
    resp = await stub.LeaveLobby(process_pb2.UserRef(user_id=str(user.id)))
    return _status_error(resp)


async def _h_lobby_seat(stub: Any, user: User, cmd: LobbySeat) -> ServerEvent | None:
    resp = await stub.SeatPlayer(
        process_pb2.SeatReq(
            leader_id=str(user.id),
            target_user_id=cmd.user_id,
            pos=cmd.pos,
        )
    )
    return _status_error(resp)


async def _h_lobby_unseat(stub: Any, user: User, cmd: LobbyUnseat) -> ServerEvent | None:
    resp = await stub.UnseatPlayer(
        process_pb2.UnseatReq(leader_id=str(user.id), pos=cmd.pos)
    )
    return _status_error(resp)


async def _h_lobby_kick(stub: Any, user: User, cmd: LobbyKick) -> ServerEvent | None:
    resp = await stub.KickFromLobby(
        process_pb2.KickReq(
            leader_id=str(user.id),
            target_user_id=cmd.user_id,
        )
    )
    return _status_error(resp)


async def _h_lobby_config(stub: Any, user: User, cmd: LobbyConfig) -> ServerEvent | None:
    resp = await stub.SetLobbyConfig(
        process_pb2.SetConfigReq(
            leader_id=str(user.id),
            initial_ms=cmd.initial_ms,
            increment_ms=cmd.increment_ms,
            rated=cmd.rated,
        )
    )
    return _status_error(resp)


async def _h_queue_start(stub: Any, user: User, _: Any) -> ServerEvent | None:
    resp = await stub.StartMatchmaking(process_pb2.UserRef(user_id=str(user.id)))
    return _status_error(resp)


async def _h_queue_cancel(stub: Any, user: User, _: Any) -> ServerEvent | None:
    resp = await stub.CancelMatchmaking(process_pb2.UserRef(user_id=str(user.id)))
    return _status_error(resp)


async def _h_game_move(stub: Any, user: User, cmd: GameMove) -> ServerEvent | None:
    resp = await stub.MakeMove(
        process_pb2.MoveReq(user_id=str(user.id), uci=cmd.uci)
    )
    return _status_error(resp)


async def _h_game_resign(stub: Any, user: User, _: Any) -> ServerEvent | None:
    resp = await stub.Resign(process_pb2.UserRef(user_id=str(user.id)))
    return _status_error(resp)


HANDLERS: dict[str, Handler] = {
    "ping":          _h_ping,
    "lobby.create":  _h_lobby_create,
    "lobby.join":    _h_lobby_join,
    "lobby.leave":   _h_lobby_leave,
    "lobby.seat":    _h_lobby_seat,
    "lobby.unseat":  _h_lobby_unseat,
    "lobby.kick":    _h_lobby_kick,
    "lobby.config":  _h_lobby_config,
    "queue.start":   _h_queue_start,
    "queue.cancel":  _h_queue_cancel,
    "game.move":     _h_game_move,
    "game.resign":   _h_game_resign,
}


async def dispatch(
    stub: process_pb2_grpc.ProcessServiceStub,
    user: User,
    raw: str,
) -> ServerEvent | None:
    try:
        cmd: ClientEvent = ClientEventAdapter.validate_json(raw)
    except ValidationError as exc:
        return ErrorEvent(
            code="bad_request",
            message=json.dumps(exc.errors(include_url=False), ensure_ascii=False),
        )
    except ValueError:
        return ErrorEvent(code="bad_request", message="invalid json")

    handler = HANDLERS[cmd.type]
    try:
        return await handler(stub, user, cmd)
    except grpc.aio.AioRpcError as exc:
        logger.warning("grpc error on %s: %s", cmd.type, exc)
        return _grpc_error(exc)


def _lobby_from_pb(lobby: process_pb2.LobbyState, user_id: UUID) -> LobbyPayload:
    seats: list[Any] = []
    your_pos: int | None = None
    uid_str = str(user_id)
    for idx, seat in enumerate(lobby.seats):
        if seat.empty:
            seats.append(None)
            continue
        seats.append(
            {
                "user_id": seat.user_id,
                "username": seat.username,
                "rating": seat.rating,
            }
        )
        if seat.user_id == uid_str:
            your_pos = idx
    state: Any = "in_queue" if lobby.state == "IN_QUEUE" else "idle"
    return LobbyPayload.model_validate(
        {
            "id": lobby.id,
            "leader_id": lobby.leader_id,
            "seats": seats,
            "config": {
                "initial_ms": lobby.config.initial_ms,
                "increment_ms": lobby.config.increment_ms,
                "rated": lobby.config.rated,
            },
            "state": state,
            "your_pos": your_pos,
        }
    )


def _game_from_pb(game: process_pb2.GameState) -> GameStatePayload:
    pockets_raw = json.loads(game.pockets.json) if game.pockets.json else {
        "b0": {"w": {}, "b": {}},
        "b1": {"w": {}, "b": {}},
    }
    return GameStatePayload.model_validate(
        {
            "game_id": game.game_id,
            "board": game.board,
            "color": game.color,
            "partner_id": game.partner_id,
            "opponents": list(game.opponents),
            "fen": game.fen,
            "mate_fen": game.mate_fen,
            "pockets": pockets_raw,
            "last_move": game.last_move,
            "clocks": {
                "b0w": game.clocks.b0w,
                "b0b": game.clocks.b0b,
                "b1w": game.clocks.b1w,
                "b1b": game.clocks.b1b,
            },
            "your_turn": game.your_turn,
            "winner": game.winner,
        }
    )


def snapshot_from_pb(resp: process_pb2.SnapshotResp, user_id: UUID) -> ServerEvent:
    if not resp.ok:
        return ErrorEvent(
            code=resp.error_code or "snapshot_failed",
            message=resp.message or "",
        )
    state: SnapshotStateStr
    if resp.state == "LOBBY":
        state = "LOBBY"
    elif resp.state == "GAME":
        state = "GAME"
    else:
        state = "IDLE"
    lobby = _lobby_from_pb(resp.lobby, user_id) if resp.HasField("lobby") else None
    game = _game_from_pb(resp.game) if resp.HasField("game") else None
    return SnapshotEvent(state=state, lobby=lobby, game=game)
