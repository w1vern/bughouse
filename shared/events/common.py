from __future__ import annotations

from enum import IntEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class WsMsgType(IntEnum):
    # client base
    PING = 0
    REQ_SYNC = 1
    # server base
    PONG = 20
    SYNC = 21
    # client lobby
    LOBBY_CREATE = 40
    LOBBY_LEAVE = 41
    LOBBY_KICK = 42
    INVITE_SEND = 43
    INVITE_ACCEPT = 44
    INVITE_REJECT = 45
    LOBBY_CONFIG = 46
    START_MM = 48
    CANCEL_MM = 49
    # server lobby
    LOBBY_JOIN = 60
    LOBBY_KICKED = 61
    INVITE_RECEIVE = 62
    LOBBY_CONFIG_UPDATE = 63
    LOBBY_INVITE_REJECTED = 64
    LOBBY_START_MM = 65
    LOBBY_CANCEL_MM = 66
    LOBBY_PLAYER_JOIN = 67
    LOBBY_PLAYER_LEAVE = 68
    # client game
    GAME_MOVE = 80
    GAME_CHAT_MSG_SEND = 83
    GAME_RESIGN = 84
    # server game
    GAME_JOIN = 100
    GAME_MOVE_RECEIVE = 101
    GAME_CHAT_MSG_RECEIVE = 102
    GAME_END = 103
    # error
    ERROR = 999


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        serialize_by_alias=True,
    )


UserState = Literal["IDLE", "LOBBY", "GAME"]
ChessColor = Literal["white", "black"]
SlotIdx = Literal[0, 1, 2, 3]
BoardIdx = Literal[0, 1]
GameStatus = Literal["WinA", "WinB", "Draw", "Abort"]
LeaveReason = Literal["leave", "kick"]


class NoData(CamelModel):
    pass


class LobbyPlayerSlot(CamelModel):
    username: str
    rating: float


class LobbyTimeData(CamelModel):
    init_ms: int = Field(ge=0)
    incr_ms: int = Field(ge=0)


class LobbyTimeRatingData(LobbyTimeData):
    rated: bool


class LobbyData(LobbyTimeRatingData):
    in_queue: bool
    slots: list[LobbyPlayerSlot | None]
    leader: str


class LobbyUpdateSlot(CamelModel):
    idx: SlotIdx
    slot: LobbyPlayerSlot | None


class LobbyPlayerLeaveData(CamelModel):
    idx: SlotIdx
    reason: LeaveReason


class InviteData(CamelModel):
    idx: SlotIdx
    username: str


class InviteRejectedData(CamelModel):
    idx: SlotIdx
    username: str


class ClocksData(CamelModel):
    """Internal clock snapshot — NOT used on the wire (kept for helpers)."""
    model_config = {  # type: ignore[misc]
        "alias_generator": None,
        "populate_by_name": True,
        "extra": "forbid",
        "serialize_by_alias": False,
    }
    b0w: int = Field(ge=0)
    b0b: int = Field(ge=0)
    b1w: int = Field(ge=0)
    b1b: int = Field(ge=0)


class PocketData(CamelModel):
    pawn: int = 0
    knight: int = 0
    bishop: int = 0
    rook: int = 0
    queen: int = 0


class PlayerData(CamelModel):
    name: str
    rating: float
    color: ChessColor
    clock: int = Field(ge=0)
    pocket: PocketData


class BoardData(CamelModel):
    fen: str
    players: tuple[PlayerData, PlayerData]
    last_move: tuple[str, str] | tuple[str] | None = None


class BughouseData(CamelModel):
    boards: tuple[BoardData, BoardData]
    status: GameStatus | None = None
    timestamp: int


class GameMoveData(CamelModel):
    idx: BoardIdx
    move: str


class GameMoveServerData(CamelModel):
    idx: BoardIdx
    move: str
    white: int = Field(ge=0)
    black: int = Field(ge=0)


class GameEndData(CamelModel):
    status: GameStatus
    rating_changes: dict[str, float]


class SyncData(CamelModel):
    state: UserState
    lobby: LobbyData | None = None
    game: BughouseData | None = None


class ErrorData(CamelModel):
    code: str | None = None
    message: str | None = None
