

import json
from datetime import timedelta
from enum import Enum
from uuid import UUID
from typing import Any


class States(str, Enum):
    default = "default"
    lobby = "lobby"
    game = "game"
    after_game = "after_game"


class Lobby:
    def __init__(self) -> None:
        self.pos1: UUID | None = None
        self.pos2: UUID | None = None
        self.pos3: UUID | None = None
        self.pos4: UUID | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "pos1": str(self.pos1) if self.pos1 else None,
            "pos2": str(self.pos2) if self.pos2 else None,
            "pos3": str(self.pos3) if self.pos3 else None,
            "pos4": str(self.pos4) if self.pos4 else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Lobby":
        lobby = cls()
        lobby.pos1 = UUID(data["pos1"]) if data.get("pos1") else None
        lobby.pos2 = UUID(data["pos2"]) if data.get("pos2") else None
        lobby.pos3 = UUID(data["pos3"]) if data.get("pos3") else None
        lobby.pos4 = UUID(data["pos4"]) if data.get("pos4") else None
        return lobby


class Move:
    def __init__(self, notation: str, time_diff: timedelta) -> None:
        self.notation = notation
        self.time_diff = time_diff

    def to_dict(self) -> dict[str, object]:
        return {
            "notation": self.notation,
            "time_diff": self.time_diff.total_seconds(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Move":
        return cls(
            notation=data["notation"],
            time_diff=timedelta(seconds=data["time_diff"]),
        )


class Game:
    def __init__(self) -> None:
        self.moves1: list[Move] = []
        self.moves2: list[Move] = []

    def to_dict(self) -> dict[str, object]:
        return {
            "moves1": [move.to_dict() for move in self.moves1],
            "moves2": [move.to_dict() for move in self.moves2],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Game":
        game = cls()
        game.moves1 = [Move.from_dict(m) for m in data.get("moves1", [])]
        game.moves2 = [Move.from_dict(m) for m in data.get("moves2", [])]
        return game


class State:
    def __init__(self) -> None:
        self.state: States = States.default
        self.lobby: Lobby | None = None
        self.game: Game | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "lobby": self.lobby.to_dict() if self.lobby is not None else None,
            "game": self.game.to_dict() if self.game is not None else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "State":
        state_obj = cls()
        state_obj.state = States(data["state"])
        state_obj.lobby = Lobby.from_dict(
            data["lobby"]) if data.get("lobby") else None
        state_obj.game = Game.from_dict(
            data["game"]) if data.get("game") else None
        return state_obj

    def to_json(self, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "State":
        data = json.loads(json_str)
        return cls.from_dict(data)
