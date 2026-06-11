
from uuid import UUID

from sqlalchemy import ForeignKey, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel
from .user import User


class Bot(BaseModel):
    __tablename__ = "bots"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)

    enabled: Mapped[bool] = mapped_column(default=False, server_default=false())

    # Stage 2 (engine) — stored now, not yet wired into move selection.
    engine_enabled: Mapped[bool] = mapped_column(
        default=False, server_default=false())
    strength: Mapped[int] = mapped_column(default=0, server_default="0")

    user: Mapped[User] = relationship(
        lazy="selectin",
        foreign_keys=[user_id],
        back_populates="bot",
    )
