
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
