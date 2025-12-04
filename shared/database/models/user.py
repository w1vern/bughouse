
from secrets import token_urlsafe

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from .base import BaseModel


class User(BaseModel):
    __tablename__ = "users"

    email: Mapped[str | None] = mapped_column(unique=True, nullable=True)
    username: Mapped[str]
    password_hash: Mapped[str | None] = mapped_column(nullable=True)

    rating: Mapped[float]
    sigma: Mapped[float]

    secret: Mapped[str] = mapped_column(default=token_urlsafe)
