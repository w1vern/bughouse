
from .base import BaseNotFoundException


class UserNotFoundException(BaseNotFoundException):
    def __init__(self) -> None:
        super().__init__(detail="User not found")


class RankingParamNotFoundException(BaseNotFoundException):
    def __init__(self) -> None:
        super().__init__(detail="Ranking param not found")


class GameNotFoundException(BaseNotFoundException):
    def __init__(self) -> None:
        super().__init__(detail="Game not found")


class BotNotFoundException(BaseNotFoundException):
    def __init__(self) -> None:
        super().__init__(detail="Bot not found")


class OAuthProviderNotSupportedException(BaseNotFoundException):
    def __init__(self, provider: str) -> None:
        super().__init__(detail=f"OAuth provider '{provider}' is not supported")


class OAuthLinkNotFoundException(BaseNotFoundException):
    def __init__(self, provider: str) -> None:
        super().__init__(detail=f"Provider '{provider}' is not linked to this account")
