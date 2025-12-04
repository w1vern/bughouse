
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class RankingParam(Base):
    __tablename__ = "ranking_params"

    name: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[float]
