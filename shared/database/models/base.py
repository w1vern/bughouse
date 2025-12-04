
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
)
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    ...

class BaseModel(Base):
    __abstract__ = True
    
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    created_date: Mapped[datetime] = mapped_column(server_default=func.now())
    deleted_date: Mapped[datetime | None] = mapped_column(
        nullable=True, default=None)
