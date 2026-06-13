
import asyncio
import secrets

from sqlalchemy import text

from shared.database import (
    BOT_USER_EMAILS,
    BOT_USER_IDS,
    BOT_USER_USERNAMES,
    UserRepository,
    session_manager,
)
from shared.infrastructure import env_config, get_redis_client, setup_logger

logger = setup_logger(__name__)

# Ephemeral presence/runtime keys. They describe who is connected/available
# right now, so on a fresh stack start they must be empty — anything left over
# from a previous (possibly unclean) shutdown is stale. Bootstrap runs once,
# before backend/core accept traffic, so this is the safe place to wipe them.
# Humans re-register on reconnect; bots are re-enabled by a superadmin.
ACTIVE_PLAYER_KEY = "active_player"
BOT_ENGINE_ON_KEY = "bot:engine_on"
ONLINE_KEY_PATTERN = "ws:online:*"


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


async def create_bot_users(ur: UserRepository) -> None:
    # Reserved foreign-key-target rows for persisting bot games. Logical bots
    # (names/levels) live in env config + Redis, not here.
    for id, username, email in zip(
        BOT_USER_IDS, BOT_USER_USERNAMES, BOT_USER_EMAILS
    ):
        if await ur.get_by_id(id) is not None:
            continue
        await ur.create(
            id=id,
            email=email,
            username=username,
            password=secrets.token_urlsafe(),
            rating=env_config.ranking.mu,
            sigma=env_config.ranking.sigma,
            color=0,
            is_bot=True
        )


async def clear_stale_presence() -> None:
    """Wipe leftover presence/availability state from a previous run.

    Clears the available-players set and the bot engine-on set, plus any stale
    per-connection online locks, so nobody (human or bot) lingers as "available"
    after a restart.
    """
    redis = get_redis_client(env_config.redis.backend)
    try:
        await redis.delete(ACTIVE_PLAYER_KEY, BOT_ENGINE_ON_KEY)
        online_keys = [
            key async for key in redis.scan_iter(
                match=ONLINE_KEY_PATTERN, count=100
            )
        ]
        if online_keys:
            await redis.delete(*online_keys)
        logger.info("cleared stale presence (%d online locks)", len(online_keys))
    except Exception:
        logger.exception("failed to clear stale presence")
    finally:
        await redis.aclose()


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
        await create_bot_users(ur)
    await clear_stale_presence()
    logger.info("database is filled")

if __name__ == "__main__":
    asyncio.run(main())
