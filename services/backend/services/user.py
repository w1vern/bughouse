

from uuid import UUID

from ..schemas import EditUserSchema, UserSchema


class UserService:
    def __init__(
        self,

    ) -> None:
        raise NotImplementedError()

    @classmethod
    def depends(
        cls,
    ) -> 'UserService':
        raise NotImplementedError()

    async def get_by_id(
        self,
        id: UUID
    ) -> UserSchema | None:
        raise NotImplementedError()

    async def get_all(
        self,
        limit: int | None,
        offset: int | None
    ) -> list[UserSchema]:
        raise NotImplementedError()

    async def count(
        self
    ) -> int:
        raise NotImplementedError()

    async def me(
        self
    ) -> UserSchema:
        raise NotImplementedError()

    async def update_user(
        self,
        id: UUID,
        edit_schema: EditUserSchema
    ) -> None:
        raise NotImplementedError()
