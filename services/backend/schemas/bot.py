
from pydantic import BaseModel

from shared.infrastructure import BotConfig


class BotSchema(BaseModel):
    name: str
    mu: float
    sigma: float
    enabled: bool
    engine_enabled: bool

    @classmethod
    def from_config(
        cls,
        config: BotConfig,
        *,
        enabled: bool,
        engine_enabled: bool
    ) -> "BotSchema":
        return cls(
            name=config.name,
            mu=config.mu,
            sigma=config.sigma,
            enabled=enabled,
            engine_enabled=engine_enabled
        )


class EditBotSchema(BaseModel):
    enabled: bool | None = None
    engine_enabled: bool | None = None
