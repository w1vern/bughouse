from __future__ import annotations

from services.core.errors import LobbyError as _BaseLobbyError

ERR_LOBBY_NOT_FOUND = "lobby_not_found"
ERR_USER_ALREADY_IN_LOBBY = "user_already_in_lobby"
ERR_USER_NOT_IN_LOBBY = "user_not_in_lobby"
ERR_NOT_LEADER = "not_leader"
ERR_SEAT_OCCUPIED = "seat_occupied"
ERR_SEAT_OUT_OF_RANGE = "seat_out_of_range"
ERR_TARGET_NOT_IN_LOBBY = "target_not_in_lobby"
ERR_CANNOT_KICK_SELF = "cannot_kick_self"
ERR_LOBBY_FULL = "lobby_full"
ERR_BAD_CONFIG = "bad_config"
ERR_CANNOT_MODIFY_WHILE_IN_QUEUE = "cannot_modify_while_in_queue"
ERR_USER_NOT_FOUND = "user_not_found"
ERR_INVITE_TARGET_BUSY = "invite_target_busy"
ERR_INVITE_TARGET_OFFLINE = "invite_target_offline"
ERR_INVITE_NOT_FOUND = "invite_not_found"
ERR_INVITE_SELF = "invite_self"
ERR_NOT_A_BOT = "not_a_bot"
ERR_RATED_WITH_BOT = "rated_with_bot"


class LobbyError(_BaseLobbyError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message=message, code=code)

    @classmethod
    def not_found(cls) -> "LobbyError":
        return cls(ERR_LOBBY_NOT_FOUND, "Lobby not found")

    @classmethod
    def user_already_in_lobby(cls) -> "LobbyError":
        return cls(ERR_USER_ALREADY_IN_LOBBY, "User already in a lobby")

    @classmethod
    def user_not_in_lobby(cls) -> "LobbyError":
        return cls(ERR_USER_NOT_IN_LOBBY, "User is not in this lobby")

    @classmethod
    def not_leader(cls) -> "LobbyError":
        return cls(ERR_NOT_LEADER, "Only the lobby leader can perform this action")

    @classmethod
    def seat_occupied(cls) -> "LobbyError":
        return cls(ERR_SEAT_OCCUPIED, "Target seat is already occupied")

    @classmethod
    def seat_out_of_range(cls) -> "LobbyError":
        return cls(ERR_SEAT_OUT_OF_RANGE, "Seat index must be in {0, 1, 2, 3}")

    @classmethod
    def target_not_in_lobby(cls) -> "LobbyError":
        return cls(ERR_TARGET_NOT_IN_LOBBY, "Target user is not in the lobby")

    @classmethod
    def cannot_kick_self(cls) -> "LobbyError":
        return cls(ERR_CANNOT_KICK_SELF, "Leader cannot kick themselves")

    @classmethod
    def lobby_full(cls) -> "LobbyError":
        return cls(ERR_LOBBY_FULL, "Lobby is full")

    @classmethod
    def bad_config(cls, message: str = "Invalid lobby config") -> "LobbyError":
        return cls(ERR_BAD_CONFIG, message)

    @classmethod
    def cannot_modify_while_in_queue(cls) -> "LobbyError":
        return cls(ERR_CANNOT_MODIFY_WHILE_IN_QUEUE, "Lobby is in queue and cannot be modified")

    @classmethod
    def user_not_found(cls) -> "LobbyError":
        return cls(ERR_USER_NOT_FOUND, "User not found in the database")

    @classmethod
    def invite_target_busy(cls) -> "LobbyError":
        return cls(ERR_INVITE_TARGET_BUSY, "Invitee is already in a lobby or game")

    @classmethod
    def invite_target_offline(cls) -> "LobbyError":
        return cls(ERR_INVITE_TARGET_OFFLINE, "Invitee is not online")

    @classmethod
    def invite_not_found(cls) -> "LobbyError":
        return cls(ERR_INVITE_NOT_FOUND, "No matching invite")

    @classmethod
    def invite_self(cls) -> "LobbyError":
        return cls(ERR_INVITE_SELF, "Cannot invite yourself")

    @classmethod
    def not_a_bot(cls) -> "LobbyError":
        return cls(ERR_NOT_A_BOT, "Target user is not a bot")

    @classmethod
    def rated_with_bot(cls) -> "LobbyError":
        return cls(ERR_RATED_WITH_BOT, "Bots can only play unrated games")
