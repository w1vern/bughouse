from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID


@dataclass(slots=True)
class Seat:
    username: str
    rating: float
    is_bot: bool = False


@dataclass(slots=True)
class LobbyConfig:
    clock_time: int = 180_000
    incr: int = 2_000
    rated: bool = False


class LobbyState(Enum):
    IDLE = "idle"
    IN_QUEUE = "in_queue"
    IN_GAME = "in_game"


@dataclass(slots=True)
class Lobby:
    id: UUID
    leader: str
    seats: list[Seat | None]
    config: LobbyConfig
    state: LobbyState

    @property
    def usernames(self) -> list[str]:
        return [s.username for s in self.seats if s is not None]

    @property
    def human_usernames(self) -> list[str]:
        return [s.username for s in self.seats if s is not None and not s.is_bot]

    @property
    def has_human(self) -> bool:
        return any(s is not None and not s.is_bot for s in self.seats)

    @property
    def has_bot(self) -> bool:
        return any(s is not None and s.is_bot for s in self.seats)

    @property
    def size(self) -> int:
        return sum(1 for s in self.seats if s is not None)

    def seat_of(self, username: str) -> int | None:
        for i, s in enumerate(self.seats):
            if s is not None and s.username == username:
                return i
        return None
