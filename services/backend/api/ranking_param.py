
from fastapi import APIRouter, Depends

from ..schemas import EditRankingParamSchema, RankingParamSchema
from ..services import RankingParamService

router = APIRouter(prefix="/ranking_params", tags=["ranking_params"])


@router.get(
    path="",
    description="Get all ranking params"
)
async def get_all(
    rp_service: RankingParamService = Depends(RankingParamService.depends)
) -> list[RankingParamSchema]:
    return await rp_service.get_all()


@router.patch(
    path="/{name}",
    description="Edit ranking param"
)
async def edit(
    name: str,
    erp_schema: EditRankingParamSchema,
    rp_service: RankingParamService = Depends(RankingParamService.depends)
) -> None:
    return await rp_service.edit(name, erp_schema)
