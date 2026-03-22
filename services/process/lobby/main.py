
from dataclasses import dataclass
import time

from uuid import UUID



@dataclass
class Player:
    id: UUID
    rating: float
    color_balance: int = 0

@dataclass
class Lobby:
    id: UUID
    players: list[Player | None]
    players_count: int
    