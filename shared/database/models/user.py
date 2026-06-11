
from secrets import token_urlsafe
from typing import TYPE_CHECKING

from sqlalchemy import false
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from .base import BaseModel

if TYPE_CHECKING:
    from .bot import Bot


class User(BaseModel):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        unique=True,
        index=True
    )
    username: Mapped[str] = mapped_column(
        unique=True,
        index=True
    )
    password_hash: Mapped[str] = mapped_column()

    rating: Mapped[float]
    sigma: Mapped[float]
    color: Mapped[int]

    secret: Mapped[str] = mapped_column(default=token_urlsafe)

    is_bot: Mapped[bool] = mapped_column(default=False, server_default=false())

    bot: Mapped["Bot | None"] = relationship(
        lazy="selectin",
        back_populates="user",
    )
