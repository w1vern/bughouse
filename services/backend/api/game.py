
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from ..schemas import GameSchema
from ..services import GameService

router = APIRouter(prefix="/games", tags=["games"])


@router.get(
    path="",
    summary="Get all games"
)
async def get_all(
    user_id: UUID | None = Query(None, description="User id"),
    limit: int | None = Query(None,
                              ge=1,
                              description="Number of items to return"),
    offset: int | None = Query(None,
                               ge=0,
                               description="From which index to start"),
    game_service: GameService = Depends(GameService.depends)
) -> list[GameSchema]:
    return await game_service.get_all(
        user_id=user_id,
        offset=offset,
        limit=limit
    )


@router.get(
    path="/count",
    summary="Get count of games"
)
async def count(
    user_id: UUID | None = Query(None, description="User id"),
    game_service: GameService = Depends(GameService.depends)
) -> int:
    return await game_service.count(user_id=user_id)


@router.get(
    path="/{id}",
    summary="Get game by id"
)
async def get_by_id(
    id: UUID,
    game_service: GameService = Depends(GameService.depends)
) -> GameSchema | None:
    return await game_service.get_by_id(id=id)
