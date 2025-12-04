
from datetime import (
    UTC,
    datetime,
)

from fastapi import (
    Cookie,
    Depends,
)
from redis.asyncio import Redis

from shared.database import User, UserRepository

from ..depends import get_user_repo
from ..exceptions import (
    AccessTokenCorruptedException,
    AccessTokenExpiredException,
    AccessTokenInvalidatedException,
    AccessTokenMissingException,
    SendFeedbackToAdminException
)
from ..redis import (
    RedisType,
    get_redis_client,
)
from ..schemas import UserSchema
from ..token import AccessToken


async def get_user(access_token: str | None = Cookie(default=None),
                   redis: Redis = Depends(get_redis_client)
                   ) -> UserSchema:
    if access_token is None:
        raise AccessTokenMissingException()
    access = AccessToken.from_token(access_token)
    current_time = datetime.now(UTC).replace(tzinfo=None)
    if access.created_date > current_time or access.created_date + access.lifetime < current_time:
        raise AccessTokenExpiredException()
    if await redis.exists(f"{RedisType.invalidated_access_token.value}:{access.user.id}"):
        raise AccessTokenInvalidatedException()
    if not access.user:
        raise AccessTokenCorruptedException()
    return access.user


async def get_db_user(user: UserSchema,
                      ur: UserRepository = Depends(get_user_repo)
                      ) -> User:
    user_db = await ur.get_by_id(user.id)
    if user_db is None:
        raise SendFeedbackToAdminException()
    return user_db
