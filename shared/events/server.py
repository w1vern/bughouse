from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from .common import (
    ClocksPayload,
    EndReasonStr,
    EventModel,
    GameResultStr,
    GameStatePayload,
    LobbyConfigPayload,
    LobbyPayload,
    LobbyStateStr,
    PocketsPayload,
    SeatPayload,
    SnapshotStateStr,
)


class Pong(EventModel):
    type: Literal["pong"] = "pong"


class ErrorEvent(EventModel):
    type: Literal["error"] = "error"
    code: str
    message: str = ""


class SnapshotEvent(EventModel):
    type: Literal["snapshot"] = "snapshot"
    state: SnapshotStateStr
    lobby: LobbyPayload | None = None
    game: GameStatePayload | None = None


class LobbyStateEvent(EventModel):
    type: Literal["lobby.state"] = "lobby.state"
    id: str
    leader_id: str
    seats: list[SeatPayload | None]
    config: LobbyConfigPayload
    state: LobbyStateStr
    your_pos: int | None = None


class LobbyDeleted(EventModel):
    type: Literal["lobby.deleted"] = "lobby.deleted"
    reason: str


class QueueStarted(EventModel):
    type: Literal["queue.started"] = "queue.started"


class QueueCancelled(EventModel):
    type: Literal["queue.cancelled"] = "queue.cancelled"


class QueueMatchFound(EventModel):
    type: Literal["queue.match_found"] = "queue.match_found"
    game_id: str


class GameStart(EventModel):
    type: Literal["game.start"] = "game.start"
    game_id: str
    board: int = Field(ge=0, le=1)
    color: int = Field(ge=0, le=1)
    partner_id: str
    opponents: list[str]
    initial_ms: int = Field(ge=0)
    increment_ms: int = Field(ge=0)


class GameMoveEvent(EventModel):
    type: Literal["game.move"] = "game.move"
    board: int = Field(ge=0, le=1)
    uci: str
    fen_after: str
    pockets_after: PocketsPayload
    clocks: ClocksPayload
    next_mover_id: str


class GameEnd(EventModel):
    type: Literal["game.end"] = "game.end"
    result: GameResultStr
    reason: EndReasonStr
    rating_deltas: dict[str, float]


ServerEvent = Annotated[
    Pong
    | ErrorEvent
    | SnapshotEvent
    | LobbyStateEvent
    | LobbyDeleted
    | QueueStarted
    | QueueCancelled
    | QueueMatchFound
    | GameStart
    | GameMoveEvent
    | GameEnd,
    Field(discriminator="type"),
]

ServerEventAdapter: TypeAdapter[ServerEvent] = TypeAdapter(ServerEvent)

SERVER_EVENTS: dict[str, type[EventModel]] = {
    cls.model_fields["type"].default: cls
    for cls in (
        Pong,
        ErrorEvent,
        SnapshotEvent,
        LobbyStateEvent,
        LobbyDeleted,
        QueueStarted,
        QueueCancelled,
        QueueMatchFound,
        GameStart,
        GameMoveEvent,
        GameEnd,
    )
}
