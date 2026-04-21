from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from uuid import UUID

from ..lobby.models import LobbyConfig
from .board import BughouseBoards
from .clocks import Clocks


class GameResult(Enum):
    TEAM_A = 0
    TEAM_B = 1
    DRAW = 2
    ABORT = 3


class EndReason(Enum):
    CHECKMATE = "checkmate"
    TIMEOUT = "timeout"
    RESIGN = "resign"
    DRAW_RULE = "draw_rule"
    ABORT_NO_MOVES = "abort_no_moves"


@dataclass(slots=True)
class PlayerRef:
    user_id: UUID
    username: str
    rating_before: float
    sigma_before: float


@dataclass(slots=True)
class MoveRecord:
    board: int
    user_id: UUID
    uci: str
    ms_spent: int
    index: int


@dataclass(slots=True)
class GameObj:
    id: UUID
    players: tuple[PlayerRef, PlayerRef, PlayerRef, PlayerRef]
    boards: BughouseBoards
    clocks: Clocks
    config: LobbyConfig
    moves: list[MoveRecord] = field(default_factory=list)
    started_at: float = 0.0
    ended_at: float | None = None
    result: GameResult | None = None
    reason: EndReason | None = None
    finished: bool = False

    @property
    def user_ids(self) -> list[str]:
        return [str(p.user_id) for p in self.players]

    @property
    def game_id(self) -> str:
        return str(self.id)
