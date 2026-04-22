from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID


@dataclass(slots=True)
class Seat:
    user_id: UUID
    username: str
    rating: float


@dataclass(slots=True)
class LobbyConfig:
    initial_ms: int = 180_000
    increment_ms: int = 2_000
    rated: bool = False


class LobbyState(Enum):
    IDLE = "idle"
    IN_QUEUE = "in_queue"


@dataclass(slots=True)
class Lobby:
    id: UUID
    leader_id: UUID
    seats: list[Seat | None]
    config: LobbyConfig
    state: LobbyState

    @property
    def user_ids(self) -> list[UUID]:
        return [s.user_id for s in self.seats if s is not None]

    @property
    def size(self) -> int:
        return sum(1 for s in self.seats if s is not None)

    def seat_of(self, user_id: UUID) -> int | None:
        for i, s in enumerate(self.seats):
            if s is not None and s.user_id == user_id:
                return i
        return None
