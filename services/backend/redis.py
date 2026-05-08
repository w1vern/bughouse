
from enum import Enum

from redis.asyncio import Redis

from shared.infrastructure import env_config
from shared.infrastructure import get_redis_client as grc


class RedisType(str, Enum):
    invalidated_access_token = "invalidated_access_token"
    active_player = "active_player"


def get_redis_client() -> Redis:
    return grc(db=env_config.redis.backend)
