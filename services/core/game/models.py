from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from uuid import UUID

import chess

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


_PARTNER_POS = {0: 3, 3: 0, 1: 2, 2: 1}


@dataclass(slots=True)
class PlayerRef:
    username: str
    rating_before: float
    sigma_before: float


@dataclass(slots=True)
class MoveRecord:
    board: int
    username: str
    uci: str
    spent: int
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
    def usernames(self) -> list[str]:
        return [p.username for p in self.players]

    def pos_of(self, username: str) -> int:
        for i, p in enumerate(self.players):
            if p.username == username:
                return i
        raise KeyError(username)

    def board_of(self, username: str) -> int:
        return self.pos_of(username) // 2

    def color_of(self, username: str) -> chess.Color:
        return chess.WHITE if self.pos_of(username) % 2 == 0 else chess.BLACK

    def partner_of(self, username: str) -> str:
        return self.players[_PARTNER_POS[self.pos_of(username)]].username

    def is_turn_of(self, username: str) -> bool:
        pos = self.pos_of(username)
        board_idx = pos // 2
        expected = chess.WHITE if pos % 2 == 0 else chess.BLACK
        return self.boards.turn(board_idx) == expected
