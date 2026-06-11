
import asyncio

from sqlalchemy import text

from shared.database import BotRepository, UserRepository, session_manager
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


async def create_bots(ur: UserRepository, br: BotRepository) -> None:
    cfg = env_config.bots
    for i in range(1, cfg.count + 1):
        username = f"{cfg.username_prefix}{i}"
        user = await ur.get_by_username(username)
        if user is None:
            user = await ur.create(
                email=f"{username}@{cfg.email_domain}",
                username=username,
                password=cfg.password,
                rating=env_config.ranking.mu,
                sigma=env_config.ranking.sigma,
                color=0
            )
        if not user.is_bot:
            user.is_bot = True
        if await br.get_by_user_id(user.id) is None:
            await br.create(user_id=user.id, enabled=False)


async def main() -> None:
    await wait_for_table("users")
    await wait_for_table("bots")
    async with session_manager.context_session() as session:
        ur = UserRepository(session)
        br = BotRepository(session)
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
        await create_bots(ur, br)
    logger.info("database is filled")

if __name__ == "__main__":
    asyncio.run(main())
