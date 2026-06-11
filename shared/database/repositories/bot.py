
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Bot
from .base import BaseRepository


class BotRepository(BaseRepository[Bot]):
    def __init__(
        self,
        session: AsyncSession
    ) -> None:
        super().__init__(
            session=session,
            model=Bot
        )

    async def create(
        self,
        *,
        user_id: UUID,
        enabled: bool = False,
        engine_enabled: bool = False,
        strength: int = 0
    ) -> Bot:
        return await self._create(
            user_id=user_id,
            enabled=enabled,
            engine_enabled=engine_enabled,
            strength=strength
        )

    async def get_by_user_id(
        self,
        user_id: UUID
    ) -> Bot | None:
        stmt = (
            select(self.model)
            .where(self.model.user_id == user_id)
            .where(self.model.deleted_date == None)
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def edit(
        self,
        bot: Bot,
        *,
        enabled: bool | None = None,
        engine_enabled: bool | None = None,
        strength: int | None = None
    ) -> None:
        await self._edit(
            instance=bot,
            enabled=enabled,
            engine_enabled=engine_enabled,
            strength=strength
        )
