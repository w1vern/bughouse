
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from redis.asyncio.client import Redis
from shared.infrastructure import BootLevel, env_config

from ..redis import get_redis_client

from ..schemas import EditUserSchema, UserSchema
from ..services import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    path="/active",
    description="Get all active users"
)
async def get_active(
    user_service: UserService = Depends(UserService.depends),
    redis: Redis = Depends(get_redis_client)
) -> list[str]:
    return await user_service.get_active(redis)


@router.get(
    path="/me",
    description="Get current user"
)
async def me(
    user_service: UserService = Depends(UserService.depends)
) -> UserSchema:
    return await user_service.me()


@router.get(
    path="/{id}",
    description="Get user by id"
)
async def get_by_id(
    id: UUID,
    user_service: UserService = Depends(UserService.depends)
) -> UserSchema | None:
    return await user_service.get_by_id(id)


@router.patch(
    path="/{id}",
    description="Edit user"
)
async def edit(
    id: UUID,
    edit_schema: EditUserSchema,
    user_service: UserService = Depends(UserService.depends)
) -> None:
    return await user_service.update_user(id, edit_schema)

if env_config.boot_level is BootLevel.DEBUG:
    @router.patch(
        path="/add_active_player/{username}",
        description="test endpoint for add active players"
    )
    async def add_active(
        username: str,
        redis: Redis = Depends(get_redis_client),
        user_service: UserService = Depends(UserService.depends)
    ) -> None:
        await user_service.create_active_player(username, redis)
