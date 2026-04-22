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

    def pos_of(self, user_id: UUID) -> int:
        for i, p in enumerate(self.players):
            if p.user_id == user_id:
                return i
        raise KeyError(user_id)

    def board_of(self, user_id: UUID) -> int:
        return self.pos_of(user_id) // 2

    def color_of(self, user_id: UUID) -> chess.Color:
        return chess.WHITE if self.pos_of(user_id) % 2 == 0 else chess.BLACK

    def partner_of(self, user_id: UUID) -> UUID:
        return self.players[_PARTNER_POS[self.pos_of(user_id)]].user_id

    def opponents_of(self, user_id: UUID) -> list[UUID]:
        pos = self.pos_of(user_id)
        partner = _PARTNER_POS[pos]
        return [self.players[i].user_id for i in range(4) if i != pos and i != partner]

    def is_turn_of(self, user_id: UUID) -> bool:
        pos = self.pos_of(user_id)
        board_idx = pos // 2
        expected = chess.WHITE if pos % 2 == 0 else chess.BLACK
        return self.boards.turn(board_idx) == expected

    def winner_str(self) -> str:
        if self.result is None:
            return ""
        return self.result.name.lower()
