
from dataclasses import dataclass
import time

from uuid import UUID, uuid4


@dataclass
class Player:
    id: UUID
    rating: float
    color_balance: int = 0


@dataclass
class Lobby:
    id: UUID
    players: list[Player | None]

    def __init__(self, leader: Player) -> None:
        self.id = uuid4()
        self.players = [leader, None, None, None]

    def add_player(self, player: Player, pos: int) -> None:
        if pos < 1 or pos > 3:
            raise ValueError("pos should be 1-3")
        if self.players[pos] is not None:
            raise ValueError("pos is already occupied")
        self.players[pos] = player

    def remove_player(self, pos: int) -> None:
        if pos < 1 or pos > 3:
            raise ValueError("pos should be 1-3")
        if self.players[pos] is None:
            raise ValueError("pos is already empty")
        self.players[pos] = None

    @property
    def count(self) -> int:
        return len([p for p in self.players if p is not None])

    @property
    def rating(self) -> float:
        return sum(p.rating for p in self.players if p is not None) / self.count
