

from uuid import UUID

from fastapi import Depends

from shared.database import GameRepository, UserRepository

from ..depends import get_game_repo, get_user, get_user_repo
from ..exceptions import GameNotFoundException
from ..schemas import GameSchema, UserSchema


class GameService:
    def __init__(
        self,
        user_schema: UserSchema,
        ur: UserRepository,
        gr: GameRepository
    ) -> None:
        self.user_schema = user_schema
        self.ur = ur
        self.gr = gr

    @classmethod
    def depends(
        cls,
        user_schema: UserSchema = Depends(get_user),
        ur: UserRepository = Depends(get_user_repo),
        gr: GameRepository = Depends(get_game_repo)
    ) -> 'GameService':
        return GameService(
            user_schema=user_schema,
            ur=ur,
            gr=gr
        )

    async def get_all(
        self,
        user_id: UUID | None,
        limit: int | None,
        offset: int | None
    ) -> list[GameSchema]:
        return [GameSchema.from_db(game) for game in await self.gr.get_all(limit, offset, user_id=user_id)]

    async def count(
        self,
        user_id: UUID | None
    ) -> int:
        return await self.gr.count(user_id=user_id)

    async def get_by_id(
        self,
        id: UUID
    ) -> GameSchema | None:
        game = await self.gr.get_by_id(id)
        if game is None:
            raise GameNotFoundException()
        return GameSchema.from_db(game)
