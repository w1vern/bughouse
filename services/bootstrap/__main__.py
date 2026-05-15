
import asyncio

from sqlalchemy import text

from shared.database import UserRepository, session_manager
from shared.infrastructure import env_config, setup_logger

logger = setup_logger(__name__)


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
        user = await ur.get_by_username(env_config.superuser.username)
        if user is None:
            await ur.create(
                email=env_config.superuser.email,
                username=env_config.superuser.username,
                password=env_config.superuser.password,
                rating=env_config.ranking.mu,
                sigma=env_config.ranking.sigma,
                color=0
            )
    logger.info("database is filled")

if __name__ == "__main__":
    asyncio.run(main())
