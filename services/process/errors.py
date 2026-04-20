class ProcessError(Exception):
    code: str = "internal_error"

    def __init__(self, message: str = "", code: str | None = None) -> None:
        self.message = message or self.code
        if code:
            self.code = code
        super().__init__(self.message)


class LobbyError(ProcessError):
    code = "lobby_error"


class QueueError(ProcessError):
    code = "queue_error"


class GameError(ProcessError):
    code = "game_error"
