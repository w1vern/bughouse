
from uuid import UUID

from pydantic import BaseModel

from shared.database import Bot


class BotSchema(BaseModel):
    id: UUID
    user_id: UUID
    username: str
    rating: float
    enabled: bool
    engine_enabled: bool
    strength: int

    @classmethod
    def from_db(cls, bot: Bot) -> "BotSchema":
        return cls(
            id=bot.id,
            user_id=bot.user_id,
            username=bot.user.username,
            rating=bot.user.rating,
            enabled=bot.enabled,
            engine_enabled=bot.engine_enabled,
            strength=bot.strength,
        )


class EditBotSchema(BaseModel):
    enabled: bool | None = None
    engine_enabled: bool | None = None
    strength: int | None = None
