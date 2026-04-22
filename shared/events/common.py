from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LobbyStateStr = Literal["idle", "in_queue"]
SnapshotStateStr = Literal["IDLE", "LOBBY", "GAME"]
GameResultStr = Literal["team_a", "team_b", "draw", "abort"]
EndReasonStr = Literal[
    "checkmate", "timeout", "resign", "draw_rule", "abort_no_moves"
]
ColorInt = Literal[0, 1]
BoardIdx = Literal[0, 1]
PieceSymbol = Literal["P", "N", "B", "R", "Q"]


class EventModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SeatPayload(EventModel):
    user_id: str
    username: str
    rating: float


class LobbyConfigPayload(EventModel):
    initial_ms: int = Field(ge=0)
    increment_ms: int = Field(ge=0)
    rated: bool


class BoardPocketsPayload(EventModel):
    w: dict[PieceSymbol, int] = Field(default_factory=dict)
    b: dict[PieceSymbol, int] = Field(default_factory=dict)


class PocketsPayload(EventModel):
    b0: BoardPocketsPayload
    b1: BoardPocketsPayload


class ClocksPayload(EventModel):
    b0w: int = Field(ge=0)
    b0b: int = Field(ge=0)
    b1w: int = Field(ge=0)
    b1b: int = Field(ge=0)


class LobbyPayload(EventModel):
    id: str
    leader_id: str
    seats: list[SeatPayload | None]
    config: LobbyConfigPayload
    state: LobbyStateStr
    your_pos: int | None = None


class GameStatePayload(EventModel):
    game_id: str
    board: BoardIdx
    color: ColorInt
    partner_id: str
    opponents: list[str]
    fen: str
    mate_fen: str
    pockets: PocketsPayload
    last_move: str
    clocks: ClocksPayload
    your_turn: bool
    winner: GameResultStr | Literal[""]
