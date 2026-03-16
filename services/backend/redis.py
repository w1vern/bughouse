
from enum import Enum

from redis.asyncio import Redis

from shared.infrastructure import env_config
from shared.infrastructure import get_redis_client as grc


class RedisType(str, Enum):
    tg_code = "tg_code",
    incorrect_credentials = "incorrect_credentials",
    invalidated_access_token = "invalidated_access_token"
    state = "state"
    active_player = "active_player"


def get_redis_client() -> Redis:
    return grc(db=env_config.redis.backend)
