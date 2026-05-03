
from fastapi import Depends

from shared.database import RankingParamRepository
from shared.infrastructure import env_config

from ..depends import get_ranking_param_repo, get_user
from ..exceptions import (
    PermissionDeniedException,
    RankingParamNotFoundException
)
from ..schemas import (
    EditRankingParamSchema,
    RankingParamSchema,
    UserTokenSchema
)


class RankingParamService():
    def __init__(
        self,
        user_schema: UserTokenSchema,
        rpr: RankingParamRepository
    ) -> None:
        if user_schema.username != env_config.superuser.username:
            raise PermissionDeniedException()
        self.rpr = rpr
        self.user_schema = user_schema

    @classmethod
    async def depends(
        cls,
        user_schema: UserTokenSchema = Depends(get_user),
        rpr: RankingParamRepository = Depends(get_ranking_param_repo)
    ) -> 'RankingParamService':
        return RankingParamService(user_schema, rpr)

    async def get_all(
        self
    ) -> list[RankingParamSchema]:
        return RankingParamSchema.from_db_list(await self.rpr.get_all())

    async def edit(
        self,
        name: str,
        ranking_param_schema: EditRankingParamSchema
    ) -> None:
        param = await self.rpr.get_by_name(name)
        if param is None:
            raise RankingParamNotFoundException()
        await self.rpr.edit(
            param=param,
            value=ranking_param_schema.value
        )
