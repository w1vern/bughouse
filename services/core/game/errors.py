from __future__ import annotations

from services.core.errors import GameError as _BaseGameError

ERR_GAME_NOT_FOUND = "game_not_found"
ERR_NOT_IN_THIS_GAME = "not_in_this_game"
ERR_NOT_YOUR_TURN = "not_your_turn"
ERR_ILLEGAL_MOVE = "illegal_move"
ERR_GAME_ALREADY_FINISHED = "game_already_finished"


class GameError(_BaseGameError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message=message, code=code)

    @classmethod
    def not_found(cls) -> "GameError":
        return cls(ERR_GAME_NOT_FOUND, "Game not found")

    @classmethod
    def not_in_this_game(cls) -> "GameError":
        return cls(ERR_NOT_IN_THIS_GAME, "User is not a participant of this game")

    @classmethod
    def not_your_turn(cls) -> "GameError":
        return cls(ERR_NOT_YOUR_TURN, "It is not your turn on this board")

    @classmethod
    def illegal_move(cls, detail: str = "") -> "GameError":
        msg = "Illegal move"
        if detail:
            msg = f"{msg}: {detail}"
        return cls(ERR_ILLEGAL_MOVE, msg)

    @classmethod
    def already_finished(cls) -> "GameError":
        return cls(ERR_GAME_ALREADY_FINISHED, "Game is already finished")
