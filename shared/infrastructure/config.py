
import os
from enum import Enum

from pydantic import BaseModel
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


class BootLevel(str, Enum):
    DEBUG = "DEBUG"
    TEST = "TEST"
    RELEASE = "RELEASE"


class DBSettings(BaseModel):
    model_config = SettingsConfigDict(
        populate_by_name=True)

    user: str = ""
    password: str = ""
    host: str = ""
    port: int = 0
    name: str = ""


class RedisSettings(BaseModel):
    model_config = SettingsConfigDict(
        populate_by_name=True)

    host: str = ""
    port: int = 0
    login: str | None = None
    password: str | None = None
    backend: int = 0


class BackendSettings(BaseModel):
    model_config = SettingsConfigDict(
        populate_by_name=True)

    secret: str = ""
    workers: int = 0


class SuperUser(BaseModel):
    model_config = SettingsConfigDict(
        populate_by_name=True)

    email: str = ""
    username: str = ""
    password: str = ""


class RankingParams(BaseModel):
    model_config = SettingsConfigDict(
        populate_by_name=True)

    beta: float = 0
    tau: float = 0
    sigma: float = 0
    mu: float = 0
    epsilon: float = 0
    queue_wait_bonus: float = 0.001
    queue_color_weight: float = 0.01


class CoreSettings(BaseModel):
    model_config = SettingsConfigDict(
        populate_by_name=True)

    host: str = "core"
    port: int = 50051


class OAuthProviderSettings(BaseModel):
    model_config = SettingsConfigDict(
        populate_by_name=True)

    id: str = ""
    secret: str = ""


class OAuthSettings(BaseModel):
    model_config = SettingsConfigDict(
        populate_by_name=True)

    google: OAuthProviderSettings = OAuthProviderSettings()
    github: OAuthProviderSettings = OAuthProviderSettings()
    lichess: OAuthProviderSettings = OAuthProviderSettings()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", "dev.env"),
        env_nested_delimiter="_",
        extra="ignore"
    )

    db: DBSettings = DBSettings()
    redis: RedisSettings = RedisSettings()
    backend: BackendSettings = BackendSettings()
    superuser: SuperUser = SuperUser()
    ranking: RankingParams = RankingParams()
    core: CoreSettings = CoreSettings()
    oauth: OAuthSettings = OAuthSettings()
    boot_level: BootLevel = BootLevel.DEBUG

    base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:5173"


env_config = Settings()

if env_config.redis.login == "":
    env_config.redis.login = None

if env_config.redis.password == "":
    env_config.redis.password = None

if __name__ == "__main__":
    print(env_config.model_dump_json(indent=2))
