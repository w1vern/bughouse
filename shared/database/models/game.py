
from typing import TYPE_CHECKING

from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel

if TYPE_CHECKING:
    from .game_user import GameUser
    from .move import Move


class Game(BaseModel):
    __tablename__ = "games"

    result: Mapped[int]
    game_time: Mapped[float]
    increment: Mapped[float]
    rated: Mapped[bool]
    end_reason: Mapped[str | None] = mapped_column(nullable=True)

    moves: Mapped[list['Move']] = relationship(
        lazy='selectin', back_populates='game', order_by='Move.index')
    game_users: Mapped[list['GameUser']] = relationship(
        lazy='selectin', back_populates='game'
    )
