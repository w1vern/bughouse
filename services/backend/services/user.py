
from uuid import UUID

from fastapi import Depends
from redis.asyncio.client import Redis

from shared.database import User, UserRepository
from shared.infrastructure import setup_logger

from ..depends import get_user, get_user_repo
from ..exceptions import (
    PasswordsDoNotMatchException,
    PermissionDeniedException,
    UserNotFoundException
)
from ..redis import RedisType
from ..schemas import EditUserSchema, UserSchema

logger = setup_logger(__name__)


class UserService:
    def __init__(
        self,
        user_schema: UserSchema,
        ur: UserRepository
    ) -> None:
        self.ur = ur
        self.user_schema = user_schema

    @classmethod
    def depends(
        cls,
        user_schema: UserSchema = Depends(get_user),
        ur: UserRepository = Depends(get_user_repo)
    ) -> 'UserService':
        return UserService(user_schema=user_schema, ur=ur)

    async def get_by_id(
        self,
        id: UUID
    ) -> UserSchema | None:
        user = await self.ur.get_by_id(id)
        if user is None:
            raise UserNotFoundException()
        return UserSchema.from_db(user)

    async def me(
        self
    ) -> UserSchema:
        logger.debug("test print")
        return self.user_schema

    async def update_user(
        self,
        id: UUID,
        edit_schema: EditUserSchema
    ) -> None:
        if edit_schema.password != edit_schema.repeat_password:
            raise PasswordsDoNotMatchException()
        if self.user_schema.id != id:
            raise PermissionDeniedException()
        user = await self.ur.get_by_id(id)
        assert user is not None, "User cannot be None"
        await self.ur.edit(
            user,
            email=edit_schema.email,
            username=edit_schema.username,
            password=edit_schema.password
        )

    async def get_by_username(
        self,
        username: str
    ) -> UserSchema:
        user = await self.ur.get_by_username(username)
        if user is None:
            raise UserNotFoundException()
        return UserSchema.from_db(user)

    async def get_active(
        self,
        redis: Redis
    ) -> list[str]:
        usernames: set[str] = await redis.smembers(RedisType.active_player.value) # type: ignore
        return list(usernames)

    async def create_active_player(
        self,
        username: str,
        redis: Redis
    ) -> None:
        await redis.sadd(RedisType.active_player.value, username) # type: ignore
