class coreError(Exception):
    code: str = "internal_error"

    def __init__(self, message: str = "", code: str | None = None) -> None:
        self.message = message or self.code
        if code:
            self.code = code
        super().__init__(self.message)


class LobbyError(coreError):
    code = "lobby_error"


class QueueError(coreError):
    code = "queue_error"


class GameError(coreError):
    code = "game_error"
