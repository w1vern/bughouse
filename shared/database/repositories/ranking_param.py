
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import RankingParam


class RankingParamRepository():
    def __init__(
        self,
        session: AsyncSession
    ) -> None:
        self.session = session

    async def create(
        self,
        *,
        name: str,
        value: float
    ) -> RankingParam:
        rp = RankingParam(name=name, value=value)
        self.session.add(rp)
        await self.session.flush()
        return rp

    async def get_by_name(
        self,
        name: str
    ) -> RankingParam | None:
        stmt = select(RankingParam).where(RankingParam.name == name).limit(1)
        return await self.session.scalar(stmt)

    async def get_all(
        self
    ) -> list[RankingParam]:
        stmt = select(RankingParam)
        return list((await self.session.scalars(stmt)).all())

    async def edit(
        self,
        name: str,
        value: float
    ) -> None:
        rp = await self.get_by_name(name)
        if rp is None:
            raise Exception("RankingParam not found")
        rp.value = value
        await self.session.flush()
