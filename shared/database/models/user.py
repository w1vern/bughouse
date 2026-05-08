
from secrets import token_urlsafe

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from .base import BaseModel


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
