from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from .common import EventModel


class Ping(EventModel):
    type: Literal["ping"] = "ping"


class LobbyCreate(EventModel):
    type: Literal["lobby.create"] = "lobby.create"


class LobbyJoin(EventModel):
    type: Literal["lobby.join"] = "lobby.join"
    lobby_id: str


class LobbyLeave(EventModel):
    type: Literal["lobby.leave"] = "lobby.leave"


class LobbySeat(EventModel):
    type: Literal["lobby.seat"] = "lobby.seat"
    user_id: str
    pos: int = Field(ge=0, le=3)


class LobbyUnseat(EventModel):
    type: Literal["lobby.unseat"] = "lobby.unseat"
    pos: int = Field(ge=0, le=3)


class LobbyKick(EventModel):
    type: Literal["lobby.kick"] = "lobby.kick"
    user_id: str


class LobbyConfig(EventModel):
    type: Literal["lobby.config"] = "lobby.config"
    initial_ms: int = Field(ge=0)
    increment_ms: int = Field(ge=0)
    rated: bool


class QueueStart(EventModel):
    type: Literal["queue.start"] = "queue.start"


class QueueCancel(EventModel):
    type: Literal["queue.cancel"] = "queue.cancel"


class GameMove(EventModel):
    type: Literal["game.move"] = "game.move"
    uci: str


class GameResign(EventModel):
    type: Literal["game.resign"] = "game.resign"


ClientEvent = Annotated[
    Ping
    | LobbyCreate
    | LobbyJoin
    | LobbyLeave
    | LobbySeat
    | LobbyUnseat
    | LobbyKick
    | LobbyConfig
    | QueueStart
    | QueueCancel
    | GameMove
    | GameResign,
    Field(discriminator="type"),
]

ClientEventAdapter: TypeAdapter[ClientEvent] = TypeAdapter(ClientEvent)

CLIENT_EVENTS: dict[str, type[EventModel]] = {
    cls.model_fields["type"].default: cls
    for cls in (
        Ping,
        LobbyCreate,
        LobbyJoin,
        LobbyLeave,
        LobbySeat,
        LobbyUnseat,
        LobbyKick,
        LobbyConfig,
        QueueStart,
        QueueCancel,
        GameMove,
        GameResign,
    )
}
