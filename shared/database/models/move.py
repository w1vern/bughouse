
from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel
from .game import Game
from .user import User


class Move(BaseModel):
    __tablename__ = "moves"

    notation: Mapped[str]
    index: Mapped[int]
    time_to_move: Mapped[float]
    board_number: Mapped[int]

    game_id: Mapped[UUID] = mapped_column(ForeignKey("games.id"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))

    game: Mapped[Game] = relationship(lazy='raise', foreign_keys=[game_id])
    user: Mapped[User] = relationship(lazy='raise', foreign_keys=[user_id])
