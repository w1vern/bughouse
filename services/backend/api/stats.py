from datetime import date

from fastapi import APIRouter, Depends, Query

from ..schemas import (
    DailyRatingSchema,
    RatingExtremesSchema,
    StatsSchema
)
from ..services import StatsService

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get(
    path="",
    description="Get server stats"
)
async def get(
    stats_service: StatsService = Depends(StatsService.depends_core)
) -> StatsSchema:
    return await stats_service.get()


@router.get(
    path="/rating/extremes",
    description="Get current user rating extremes"
)
async def get_rating_extremes(
    stats_service: StatsService = Depends(StatsService.depends)
) -> RatingExtremesSchema:
    return await stats_service.get_rating_extremes()


@router.get(
    path="/rating/daily",
    description="Get current user daily final ratings"
)
async def get_daily_ratings(
    date_from: date = Query(..., description="Date from"),
    date_to: date = Query(..., description="Date to"),
    stats_service: StatsService = Depends(StatsService.depends)
) -> list[DailyRatingSchema]:
    return await stats_service.get_daily_ratings(
        date_from=date_from,
        date_to=date_to
    )
