
import grpc
from fastapi import Depends
from redis.asyncio.client import Redis

from shared.infrastructure import BotConfig, env_config, setup_logger
from shared.protobuf import core_pb2 as pb

from ..depends import get_superuser
from ..exceptions import (
    BotEngineRequiresEnabledException,
    BotNotFoundException
)
from ..redis import RedisType, get_redis_client
from ..schemas import BotSchema, EditBotSchema, UserTokenSchema
from ..websocket.grpc_client import AsyncCoreServiceStub, get_core_stub

logger = setup_logger(__name__)


class BotService:
    def __init__(
        self,
        redis: Redis,
        stub: AsyncCoreServiceStub
    ) -> None:
        self.redis = redis
        self.stub = stub

    @classmethod
    def depends(
        cls,
        _: UserTokenSchema = Depends(get_superuser),
        redis: Redis = Depends(get_redis_client),
        stub: AsyncCoreServiceStub = Depends(get_core_stub)
    ) -> 'BotService':
        return BotService(redis=redis, stub=stub)

    async def get_all(self) -> list[BotSchema]:
        bots: list[BotSchema] = []
        for config in env_config.bots:
            bots.append(
                BotSchema.from_config(
                    config,
                    enabled=await self._is_member(
                        RedisType.active_player, config.name),
                    engine_enabled=await self._is_member(
                        RedisType.bot_engine_on, config.name)
                )
            )
        return bots

    async def update(
        self,
        name: str,
        edit: EditBotSchema
    ) -> BotSchema:
        config = self._find(name)

        target_enabled = (
            edit.enabled
            if edit.enabled is not None
            else await self._is_member(RedisType.active_player, name)
        )
        target_engine = (
            edit.engine_enabled
            if edit.engine_enabled is not None
            else await self._is_member(RedisType.bot_engine_on, name)
        )
        # The engine cannot run for a disabled bot.
        if not target_enabled:
            if edit.engine_enabled:
                raise BotEngineRequiresEnabledException()
            target_engine = False

        await self._set_member(
            RedisType.active_player, name, target_enabled)
        await self._set_member(
            RedisType.bot_engine_on, name, target_engine)

        await self._notify_core(name)

        return BotSchema.from_config(
            config, enabled=target_enabled, engine_enabled=target_engine)

    def _find(self, name: str) -> BotConfig:
        for config in env_config.bots:
            if config.name == name:
                return config
        raise BotNotFoundException()

    async def _is_member(self, key: RedisType, name: str) -> bool:
        return bool(await self.redis.sismember(key.value, name))  # type: ignore

    async def _set_member(
        self,
        key: RedisType,
        name: str,
        member: bool
    ) -> None:
        if member:
            await self.redis.sadd(key.value, name)  # type: ignore
        else:
            await self.redis.srem(key.value, name)  # type: ignore

    async def _notify_core(self, name: str) -> None:
        try:
            await self.stub.SyncBot(pb.SyncBotReq(name=name))
        except grpc.aio.AioRpcError:
            # Redis is the source of truth; core reconciles on next sync/startup.
            logger.warning("SyncBot to core failed for %s", name)
