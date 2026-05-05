from fastapi import APIRouter, Depends

from ..schemas import StatsSchema
from ..services import StatsService

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get(
    path="",
    description="Get server stats"
)
async def get(
    stats_service: StatsService = Depends(StatsService.depends)
) -> StatsSchema:
    return await stats_service.get()
