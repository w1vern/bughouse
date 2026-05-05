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
    AUTO_ABORT = "auto_abort"
    ABORT_NO_MOVES = "abort_no_moves"


# Game-position layout (matches frontend lobby slot semantics):
#   pos 0 — leader-equivalent
#   pos 1 — leader's partner (same team)
#   pos 2 — leader's same-board opponent
#   pos 3 — partner's same-board opponent
# Topology:
#   Teammates : (0,1) and (2,3)
#   Same-board: (0,2) and (1,3)  -> board index = pos % 2
#   Color is independent of position; chosen at match composition via `color_flip`.
#   Without flip: pos 0,3 → white; pos 1,2 → black.
#   With flip:    pos 0,3 → black; pos 1,2 → white.

_PARTNER_POS: dict[int, int] = {0: 1, 1: 0, 2: 3, 3: 2}
_TEAM_OF_POS: dict[int, GameResult] = {
    0: GameResult.TEAM_A,
    1: GameResult.TEAM_A,
    2: GameResult.TEAM_B,
    3: GameResult.TEAM_B,
}


def pos_to_board(pos: int) -> int:
    return pos % 2


def pos_to_color(pos: int, color_flip: bool) -> chess.Color:
    natural_white = pos in (0, 3)
    if color_flip:
        natural_white = not natural_white
    return chess.WHITE if natural_white else chess.BLACK


def pos_for(board_idx: int, color: chess.Color, color_flip: bool) -> int:
    for pos in (0, 1, 2, 3):
        if pos_to_board(pos) == board_idx and pos_to_color(pos, color_flip) == color:
            return pos
    raise ValueError(f"no position for board={board_idx}, color={color}")


def team_of_pos(pos: int) -> GameResult:
    return _TEAM_OF_POS[pos]


def other_team(team: GameResult) -> GameResult:
    if team == GameResult.TEAM_A:
        return GameResult.TEAM_B
    if team == GameResult.TEAM_B:
        return GameResult.TEAM_A
    return team


@dataclass(slots=True)
class PlayerRef:
    username: str
    rating_before: float
    sigma_before: float
    lobby_id: UUID | None = None


@dataclass(slots=True)
class MoveRecord:
    board: int
    username: str
    uci: str
    spent: int
    index: int


@dataclass(slots=True)
class ChatRecord:
    idx: int
    username: str
    text: str
    created_at: int


def _empty_chat() -> dict[GameResult, list[ChatRecord]]:
    return {
        GameResult.TEAM_A: [],
        GameResult.TEAM_B: [],
    }


def _empty_auto_abort_at() -> dict[int, int | None]:
    return {0: None, 1: None}


@dataclass(slots=True)
class GameObj:
    id: UUID
    players: tuple[PlayerRef, PlayerRef, PlayerRef, PlayerRef]
    boards: BughouseBoards
    clocks: Clocks
    config: LobbyConfig
    color_flip: bool = False
    auto_abort_timeout: int = 0
    moves: list[MoveRecord] = field(default_factory=list)
    started_at: float = 0.0
    ended_at: float | None = None
    result: GameResult | None = None
    reason: EndReason | None = None
    finished: bool = False
    chat: dict[GameResult, list[ChatRecord]] = field(default_factory=_empty_chat)
    auto_abort_at: dict[int, int | None] = field(default_factory=_empty_auto_abort_at)

    @property
    def usernames(self) -> list[str]:
        return [p.username for p in self.players]

    def pos_of(self, username: str) -> int:
        for i, p in enumerate(self.players):
            if p.username == username:
                return i
        raise KeyError(username)

    def board_of(self, username: str) -> int:
        return pos_to_board(self.pos_of(username))

    def color_of(self, username: str) -> chess.Color:
        return pos_to_color(self.pos_of(username), self.color_flip)

    def partner_of(self, username: str) -> str:
        return self.players[_PARTNER_POS[self.pos_of(username)]].username

    def is_turn_of(self, username: str) -> bool:
        pos = self.pos_of(username)
        board_idx = pos_to_board(pos)
        expected = pos_to_color(pos, self.color_flip)
        return self.boards.turn(board_idx) == expected
