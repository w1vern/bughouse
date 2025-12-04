

from uuid import UUID

from ..schemas import GameSchema


class GameService:
    def __init__(
        self,

    ) -> None:
        raise NotImplementedError()

    @classmethod
    def depends(
        cls,
    ) -> 'GameService':
        raise NotImplementedError()

    async def get_all(
        self,
        user_id: UUID | None,
        limit: int | None,
        offset: int | None
    ) -> list[GameSchema]:
        raise NotImplementedError()

    async def count(
        self,
        user_id: UUID | None
    ) -> int:
        raise NotImplementedError()

    async def get_by_id(
        self,
        id: UUID
    ) -> GameSchema | None:
        raise NotImplementedError()
