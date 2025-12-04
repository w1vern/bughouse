
from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel
from .game import Game
from .user import User


class GameUser(BaseModel):
    __tablename__ = "game_users"

    board: Mapped[int]
    color: Mapped[int]
    rating: Mapped[float]
    diff: Mapped[float]

    game_id: Mapped[UUID] = mapped_column(ForeignKey("games.id"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))

    game: Mapped[Game] = relationship(lazy='raise', foreign_keys=[game_id])
    user: Mapped[User] = relationship(lazy='selectin', foreign_keys=[user_id])
