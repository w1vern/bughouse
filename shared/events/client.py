from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from .common import (
    CamelModel,
    GameMoveData,
    InviteData,
    LobbyTimeData,
    LobbyTimeRatingData,
    NoData,
    WsMsgType,
)

_PING = WsMsgType.PING.value
_REQ_SYNC = WsMsgType.REQ_SYNC.value
_LOBBY_CREATE = WsMsgType.LOBBY_CREATE.value
_LOBBY_LEAVE = WsMsgType.LOBBY_LEAVE.value
_LOBBY_KICK = WsMsgType.LOBBY_KICK.value
_INVITE_SEND = WsMsgType.INVITE_SEND.value
_INVITE_ACCEPT = WsMsgType.INVITE_ACCEPT.value
_INVITE_REJECT = WsMsgType.INVITE_REJECT.value
_LOBBY_CONFIG = WsMsgType.LOBBY_CONFIG.value
_START_MM = WsMsgType.START_MM.value
_CANCEL_MM = WsMsgType.CANCEL_MM.value
_GAME_MOVE = WsMsgType.GAME_MOVE.value
_GAME_CHAT_SEND = WsMsgType.GAME_CHAT_MSG_SEND.value
_GAME_RESIGN = WsMsgType.GAME_RESIGN.value


class PingMsg(CamelModel):
    type: Literal[_PING] = _PING  # type: ignore[valid-type]
    data: NoData = Field(default_factory=NoData)


class ReqSyncMsg(CamelModel):
    type: Literal[_REQ_SYNC] = _REQ_SYNC  # type: ignore[valid-type]
    data: NoData = Field(default_factory=NoData)


class LobbyCreateMsg(CamelModel):
    type: Literal[_LOBBY_CREATE] = _LOBBY_CREATE  # type: ignore[valid-type]
    data: LobbyTimeData


class LobbyLeaveMsg(CamelModel):
    type: Literal[_LOBBY_LEAVE] = _LOBBY_LEAVE  # type: ignore[valid-type]
    data: NoData = Field(default_factory=NoData)


class LobbyKickMsg(CamelModel):
    type: Literal[_LOBBY_KICK] = _LOBBY_KICK  # type: ignore[valid-type]
    data: str


class InviteSendMsg(CamelModel):
    type: Literal[_INVITE_SEND] = _INVITE_SEND  # type: ignore[valid-type]
    data: InviteData


class InviteAcceptMsg(CamelModel):
    type: Literal[_INVITE_ACCEPT] = _INVITE_ACCEPT  # type: ignore[valid-type]
    data: str


class InviteRejectMsg(CamelModel):
    type: Literal[_INVITE_REJECT] = _INVITE_REJECT  # type: ignore[valid-type]
    data: str


class LobbyConfigMsg(CamelModel):
    type: Literal[_LOBBY_CONFIG] = _LOBBY_CONFIG  # type: ignore[valid-type]
    data: LobbyTimeRatingData


class StartMMMsg(CamelModel):
    type: Literal[_START_MM] = _START_MM  # type: ignore[valid-type]
    data: NoData = Field(default_factory=NoData)


class CancelMMMsg(CamelModel):
    type: Literal[_CANCEL_MM] = _CANCEL_MM  # type: ignore[valid-type]
    data: NoData = Field(default_factory=NoData)


class GameMoveMsg(CamelModel):
    type: Literal[_GAME_MOVE] = _GAME_MOVE  # type: ignore[valid-type]
    data: GameMoveData


class GameChatSendMsg(CamelModel):
    type: Literal[_GAME_CHAT_SEND] = _GAME_CHAT_SEND  # type: ignore[valid-type]
    data: str


class GameResignMsg(CamelModel):
    type: Literal[_GAME_RESIGN] = _GAME_RESIGN  # type: ignore[valid-type]
    data: NoData = Field(default_factory=NoData)


ClientMsg = Annotated[
    PingMsg
    | ReqSyncMsg
    | LobbyCreateMsg
    | LobbyLeaveMsg
    | LobbyKickMsg
    | InviteSendMsg
    | InviteAcceptMsg
    | InviteRejectMsg
    | LobbyConfigMsg
    | StartMMMsg
    | CancelMMMsg
    | GameMoveMsg
    | GameChatSendMsg
    | GameResignMsg,
    Field(discriminator="type"),
]

ClientMsgAdapter: TypeAdapter[ClientMsg] = TypeAdapter(ClientMsg)

CLIENT_EVENTS: dict[int, type[CamelModel]] = {
    cls.model_fields["type"].default: cls
    for cls in (
        PingMsg,
        ReqSyncMsg,
        LobbyCreateMsg,
        LobbyLeaveMsg,
        LobbyKickMsg,
        InviteSendMsg,
        InviteAcceptMsg,
        InviteRejectMsg,
        LobbyConfigMsg,
        StartMMMsg,
        CancelMMMsg,
        GameMoveMsg,
        GameChatSendMsg,
        GameResignMsg,
    )
}
