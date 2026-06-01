
from uuid import UUID

from sqlalchemy import ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel
from .user import User


class AuthProvider(BaseModel):
    __tablename__ = "auth_providers"
    __table_args__ = (
        Index(
            "uq_auth_providers_provider_account",
            "provider", "provider_user_id",
            unique=True,
            postgresql_where=text("deleted_date IS NULL")
        ),
    )

    provider: Mapped[str] = mapped_column(index=True)
    provider_user_id: Mapped[str] = mapped_column(index=True)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))

    user: Mapped[User] = relationship(lazy='selectin', foreign_keys=[user_id])
