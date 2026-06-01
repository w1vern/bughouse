
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AuthProvider
from .base import BaseRepository


class AuthProviderRepository(BaseRepository[AuthProvider]):
    def __init__(
        self,
        session: AsyncSession
    ) -> None:
        super().__init__(
            session=session,
            model=AuthProvider
        )

    async def get_by_account(
        self,
        provider: str,
        provider_user_id: str
    ) -> AuthProvider | None:
        stmt = (
            select(self.model)
            .where(self.model.provider == provider)
            .where(self.model.provider_user_id == provider_user_id)
            .where(self.model.deleted_date == None)
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def create(
        self,
        *,
        provider: str,
        provider_user_id: str,
        user_id: UUID
    ) -> AuthProvider:
        return await self._create(
            provider=provider,
            provider_user_id=provider_user_id,
            user_id=user_id
        )
