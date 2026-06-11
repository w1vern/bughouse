
from uuid import UUID

from fastapi import Depends
from redis.asyncio.client import Redis

from shared.database import BotRepository
from shared.infrastructure import setup_logger

from ..depends import get_bot_repo, get_superuser
from ..exceptions import BotNotFoundException
from ..redis import RedisType, get_redis_client
from ..schemas import BotSchema, EditBotSchema, UserTokenSchema

logger = setup_logger(__name__)


class BotService:
    def __init__(
        self,
        br: BotRepository,
        redis: Redis
    ) -> None:
        self.br = br
        self.redis = redis

    @classmethod
    def depends(
        cls,
        _: UserTokenSchema = Depends(get_superuser),
        br: BotRepository = Depends(get_bot_repo),
        redis: Redis = Depends(get_redis_client)
    ) -> 'BotService':
        return BotService(br=br, redis=redis)

    async def get_all(self) -> list[BotSchema]:
        bots = await self.br.get_all()
        return [BotSchema.from_db(bot) for bot in bots]

    async def update(
        self,
        id: UUID,
        edit: EditBotSchema
    ) -> BotSchema:
        bot = await self.br.get_by_id(id)
        if bot is None:
            raise BotNotFoundException()
        await self.br.edit(
            bot,
            enabled=edit.enabled,
            engine_enabled=edit.engine_enabled,
            strength=edit.strength,
        )
        if edit.enabled is not None:
            await self._set_availability(bot.user.username, edit.enabled)
        return BotSchema.from_db(bot)

    async def _set_availability(
        self,
        username: str,
        available: bool
    ) -> None:
        if available:
            await self.redis.sadd(RedisType.active_player.value, username)  # type: ignore
        else:
            await self.redis.srem(RedisType.active_player.value, username)  # type: ignore
