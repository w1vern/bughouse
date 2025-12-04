
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database import (
    GameRepository,
    RankingParamRepository,
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


async def get_ranking_param_repo(
    session: AsyncSession = Depends(get_session)
) -> RankingParamRepository:
    return RankingParamRepository(session)
