from __future__ import annotations

from services.core.errors import QueueError as _BaseQueueError

ERR_ALREADY_IN_QUEUE = "already_in_queue"
ERR_NOT_IN_QUEUE = "not_in_queue"
ERR_BAD_LOBBY_SIZE = "bad_lobby_size"
ERR_BAD_LOBBY_STATE = "bad_lobby_state"
ERR_RATED_THREE_PLAYERS = "rated_three_players"


class QueueError(_BaseQueueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message=message, code=code)

    @classmethod
    def already_in_queue(cls) -> "QueueError":
        return cls(ERR_ALREADY_IN_QUEUE, "Lobby is already in queue")

    @classmethod
    def not_in_queue(cls) -> "QueueError":
        return cls(ERR_NOT_IN_QUEUE, "Lobby is not in queue")

    @classmethod
    def bad_lobby_size(cls) -> "QueueError":
        return cls(ERR_BAD_LOBBY_SIZE, "Lobby size must be in {1, 2, 3, 4}")

    @classmethod
    def bad_lobby_state(cls) -> "QueueError":
        return cls(ERR_BAD_LOBBY_STATE, "Lobby is not in a state that can be queued")

    @classmethod
    def rated_three_players(cls) -> "QueueError":
        return cls(ERR_RATED_THREE_PLAYERS, "Rated matches require 1, 2 or 4 players")
