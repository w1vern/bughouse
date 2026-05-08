
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database import (
    GameRepository,
    UserRepository,
    session_manager
)


async def get_session(
    session: AsyncSession = Depends(session_manager.session)
) -> AsyncSession:
    return session


async def get_user_repo(
    session: AsyncSession = Depends(get_session)
) -> UserRepository:
    return UserRepository(session)


async def get_game_repo(
    session: AsyncSession = Depends(get_session)
) -> GameRepository:
    return GameRepository(session)
