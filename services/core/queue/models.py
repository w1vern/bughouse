from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ..lobby.models import LobbyConfig, Seat


@dataclass(slots=True)
class QueueEntry:
    lobby_id: UUID
    size: int
    config: LobbyConfig
    enqueued_at: float
    seats: tuple[Seat | None, ...]
    sigmas: tuple[float | None, ...]
    colors: tuple[int | None, ...]
    avg_mu: float
    avg_sigma: float

    @property
    def positions(self) -> tuple[int, ...]:
        return tuple(i for i, s in enumerate(self.seats) if s is not None)
