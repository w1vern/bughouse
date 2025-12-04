
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .move import Move
    from .game_user import GameUser


class Game(BaseModel):
    __tablename__ = "games"

    result: Mapped[int]
    game_time: Mapped[float]
    increment: Mapped[float]

    moves: Mapped[list['Move']] = relationship(
        lazy='selectin', back_populates='game')
    game_users: Mapped[list['GameUser']] = relationship(
        lazy='selectin', back_populates='game'
    )
