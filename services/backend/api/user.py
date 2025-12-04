
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from ..schemas import EditUserSchema, UserSchema
from ..services import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    path="",
    description="Get all users"
)
async def get_all(
    limit: int | None = Query(
        None, ge=1, description="Number of items to return"),
    offset: int | None = Query(
        None, ge=0, description="From which index to start"),
    user_service: UserService = Depends(UserService.depends)
) -> list[UserSchema]:
    return await user_service.get_all(limit, offset)


@router.get(
    path="/count",
    description="Get count of users"
)
async def count(
    user_service: UserService = Depends(UserService.depends)
) -> int:
    return await user_service.count()


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
