from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from .common import (
    BughouseData,
    CamelModel,
    ErrorData,
    GameChatData,
    GameEndData,
    GameMoveServerData,
    InviteData,
    InviteRejectedData,
    LobbyData,
    LobbyPlayerLeaveData,
    LobbyTimeRatingData,
    LobbyUpdateSlot,
    NoData,
    SyncData,
    WsMsgType,
)

_PONG = WsMsgType.PONG.value
_SYNC = WsMsgType.SYNC.value
_LOBBY_JOIN = WsMsgType.LOBBY_JOIN.value
_LOBBY_KICKED = WsMsgType.LOBBY_KICKED.value
_INVITE_RECEIVE = WsMsgType.INVITE_RECEIVE.value
_LOBBY_CONFIG_UPDATE = WsMsgType.LOBBY_CONFIG_UPDATE.value
_LOBBY_INVITE_REJECTED = WsMsgType.LOBBY_INVITE_REJECTED.value
_LOBBY_START_MM = WsMsgType.LOBBY_START_MM.value
_LOBBY_CANCEL_MM = WsMsgType.LOBBY_CANCEL_MM.value
_LOBBY_PLAYER_JOIN = WsMsgType.LOBBY_PLAYER_JOIN.value
_LOBBY_PLAYER_LEAVE = WsMsgType.LOBBY_PLAYER_LEAVE.value
_GAME_JOIN = WsMsgType.GAME_JOIN.value
_GAME_MOVE_RECEIVE = WsMsgType.GAME_MOVE_RECEIVE.value
_GAME_CHAT_RECEIVE = WsMsgType.GAME_CHAT_MSG_RECEIVE.value
_GAME_END = WsMsgType.GAME_END.value
_ERROR = WsMsgType.ERROR.value


class PongMsg(CamelModel):
    type: Literal[_PONG] = _PONG  # type: ignore[valid-type]
    data: NoData = Field(default_factory=NoData)


class SyncMsg(CamelModel):
    type: Literal[_SYNC] = _SYNC  # type: ignore[valid-type]
    data: SyncData


class LobbyJoinMsg(CamelModel):
    type: Literal[_LOBBY_JOIN] = _LOBBY_JOIN  # type: ignore[valid-type]
    data: LobbyData


class LobbyKickedMsg(CamelModel):
    type: Literal[_LOBBY_KICKED] = _LOBBY_KICKED  # type: ignore[valid-type]
    data: NoData = Field(default_factory=NoData)


class InviteReceiveMsg(CamelModel):
    type: Literal[_INVITE_RECEIVE] = _INVITE_RECEIVE  # type: ignore[valid-type]
    data: InviteData


class LobbyConfigUpdateMsg(CamelModel):
    type: Literal[_LOBBY_CONFIG_UPDATE] = _LOBBY_CONFIG_UPDATE  # type: ignore[valid-type]
    data: LobbyTimeRatingData


class LobbyInviteRejectedMsg(CamelModel):
    type: Literal[_LOBBY_INVITE_REJECTED] = _LOBBY_INVITE_REJECTED  # type: ignore[valid-type]
    data: InviteRejectedData


class LobbyStartMMMsg(CamelModel):
    type: Literal[_LOBBY_START_MM] = _LOBBY_START_MM  # type: ignore[valid-type]
    data: NoData = Field(default_factory=NoData)


class LobbyCancelMMMsg(CamelModel):
    type: Literal[_LOBBY_CANCEL_MM] = _LOBBY_CANCEL_MM  # type: ignore[valid-type]
    data: NoData = Field(default_factory=NoData)


class LobbyPlayerJoinMsg(CamelModel):
    type: Literal[_LOBBY_PLAYER_JOIN] = _LOBBY_PLAYER_JOIN  # type: ignore[valid-type]
    data: LobbyUpdateSlot


class LobbyPlayerLeaveMsg(CamelModel):
    type: Literal[_LOBBY_PLAYER_LEAVE] = _LOBBY_PLAYER_LEAVE  # type: ignore[valid-type]
    data: LobbyPlayerLeaveData


class GameJoinMsg(CamelModel):
    type: Literal[_GAME_JOIN] = _GAME_JOIN  # type: ignore[valid-type]
    data: BughouseData


class GameMoveReceiveMsg(CamelModel):
    type: Literal[_GAME_MOVE_RECEIVE] = _GAME_MOVE_RECEIVE  # type: ignore[valid-type]
    data: GameMoveServerData


class GameChatReceiveMsg(CamelModel):
    type: Literal[_GAME_CHAT_RECEIVE] = _GAME_CHAT_RECEIVE  # type: ignore[valid-type]
    data: GameChatData


class GameEndMsg(CamelModel):
    type: Literal[_GAME_END] = _GAME_END  # type: ignore[valid-type]
    data: GameEndData


class ErrorMsg(CamelModel):
    type: Literal[_ERROR] = _ERROR  # type: ignore[valid-type]
    data: ErrorData


ServerMsg = Annotated[
    PongMsg
    | SyncMsg
    | LobbyJoinMsg
    | LobbyKickedMsg
    | InviteReceiveMsg
    | LobbyConfigUpdateMsg
    | LobbyInviteRejectedMsg
    | LobbyStartMMMsg
    | LobbyCancelMMMsg
    | LobbyPlayerJoinMsg
    | LobbyPlayerLeaveMsg
    | GameJoinMsg
    | GameMoveReceiveMsg
    | GameChatReceiveMsg
    | GameEndMsg
    | ErrorMsg,
    Field(discriminator="type"),
]

ServerMsgAdapter: TypeAdapter[ServerMsg] = TypeAdapter(ServerMsg)

SERVER_EVENTS: dict[int, type[CamelModel]] = {
    cls.model_fields["type"].default: cls
    for cls in (
        PongMsg,
        SyncMsg,
        LobbyJoinMsg,
        LobbyKickedMsg,
        InviteReceiveMsg,
        LobbyConfigUpdateMsg,
        LobbyInviteRejectedMsg,
        LobbyStartMMMsg,
        LobbyCancelMMMsg,
        LobbyPlayerJoinMsg,
        LobbyPlayerLeaveMsg,
        GameJoinMsg,
        GameMoveReceiveMsg,
        GameChatReceiveMsg,
        GameEndMsg,
        ErrorMsg,
    )
}


def dump(msg: CamelModel) -> str:
    return msg.model_dump_json(by_alias=True)
