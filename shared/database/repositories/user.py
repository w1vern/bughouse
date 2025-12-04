
import secrets

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from .base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(
        self,
        session: AsyncSession
    ) -> None:
        super().__init__(
            session=session,
            model=User
        )

    @staticmethod
    def _get_hash(
        password_hash: str | None
    ) -> str | None:
        return (
            bcrypt.hashpw(
                password_hash.encode(),
                bcrypt.gensalt()).decode()
            if password_hash is not None else None
        )

    @staticmethod
    async def check_password(
        user: User,
        password: str
    ) -> bool:
        if not user.password_hash:
            return False
        return bcrypt.checkpw(
            password=password.encode(),
            hashed_password=user.password_hash.encode()
        )

    async def create(
        self,
        *,
        email: str | None,
        username: str,
        password_hash: str | None,
        rating: float,
        sigma: float
    ) -> User:
        return await self._create(
            email=email,
            username=username,
            password_hash=self._get_hash(password_hash),
            rating=rating,
            sigma=sigma,
            secret=secrets.token_urlsafe()
        )

    async def get_by_email(
        self,
        email: str
    ) -> User | None:
        stmt = (
            select(self.model)
            .where(self.model.email == email)
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def edit(
        self,
        user: User,
        *,
        email: str | None = None,
        username: str | None = None,
        password_hash: str | None = None,
        rating: float | None = None,
        sigma: float | None = None
    ) -> None:
        await self._edit(
            instance=user,
            email=email,
            username=username,
            password_hash=self._get_hash(password_hash),
            rating=rating,
            sigma=sigma
        )
