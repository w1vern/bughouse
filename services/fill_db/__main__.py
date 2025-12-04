
import asyncio

from sqlalchemy import text

from shared.database import (
    RankingParamRepository,
    UserRepository,
    session_manager
)
from shared.infrastructure import env_config, setup_logger

logger = setup_logger(__name__)

default_user: dict[str, object] = {

}


default_ranking_params: list[tuple[str, float]] = [
    ("beta", env_config.ranking.beta),
    ("tau", env_config.ranking.tau),
    ("epsilon", env_config.ranking.epsilon),
    ("mu", env_config.ranking.mu),
    ("sigma", env_config.ranking.sigma)
]


async def wait_for_table(
    table_name: str,
    retries: int = 30,
    delay: int = 1
) -> None:
    for attempt in range(retries):
        try:
            async with session_manager.context_session() as session:
                result = await session.execute(text("".join([
                    "SELECT 1 ",
                    "FROM information_schema.tables ",
                    "WHERE table_name = :table_name;"
                ])), {"table_name": table_name}
                )
                exists = result.scalar()
                if exists:
                    return
        except Exception as e:
            logger.error(f"[!] Error connecting to DB: {e}")
        logger.info(
            f"[{attempt + 1}/{retries}] Waiting for table '{table_name}'...")
        await asyncio.sleep(delay)
    raise TimeoutError(f"Timed out waiting for table '{table_name}'")


async def main() -> None:
    await wait_for_table("users")
    async with session_manager.context_session() as session:
        ur = UserRepository(session)
        rpr = RankingParamRepository(session)
        users = await ur.get_all()
        if len(users) == 0:
            await ur.create(
                email=env_config.superuser.email,
                username=env_config.superuser.username,
                password_hash=env_config.superuser.password,
                rating=env_config.ranking.mu,
                sigma=env_config.ranking.sigma
            )
        params = await rpr.get_all()
        if len(params) == 0:
            for param in default_ranking_params:
                await rpr.create(name=param[0], value=param[1])

    logger.info("database is filled")

if __name__ == "__main__":
    asyncio.run(main())
