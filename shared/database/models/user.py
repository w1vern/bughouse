
from secrets import token_urlsafe

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from .base import Base


class User(Base):
    __tablename__ = "users"

    login: Mapped[str] = mapped_column(unique=True, nullable=False)
    password_hash: Mapped[str]

    rating: Mapped[float]
    sigma: Mapped[float]

    secret: Mapped[str] = mapped_column(default=token_urlsafe)
