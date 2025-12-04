

from datetime import UTC, datetime

from fastapi import Depends
from redis.asyncio import Redis

from shared.database import User, UserRepository
from shared.infrastructure import env_config

from ..config import Config
from ..depends import get_user_repo
from ..exceptions import *
from ..redis import RedisType, get_redis_client
from ..schemas import CreateUserSchema, LoginUserSchema
from ..token import AccessToken, RefreshToken
from .anti_spam import AntiSpamService


class AuthService:
    def __init__(
        self,
        ur: UserRepository,
        redis: Redis,
        anti_spam: AntiSpamService
    ) -> None:
        self.ur = ur
        self.redis = redis
        self.anti_spam = anti_spam

    @classmethod
    def depends(
        cls,
        ur: UserRepository = Depends(get_user_repo),
        redis: Redis = Depends(get_redis_client),
        anti_spam: AntiSpamService = Depends(AntiSpamService.depends)
    ) -> 'AuthService':
        return cls(ur, redis, anti_spam)

    async def register(
        self,
        register_schema: CreateUserSchema
    ) -> None:
        await self.anti_spam.increment_ip_attempts()
        if register_schema.password != register_schema.repeat_password:
            raise PasswordsDoNotMatchException()
        await self.ur.create(
            email=register_schema.email,
            username=register_schema.username,
            password_hash=register_schema.password,
            rating=env_config.ranking.mu,
            sigma=env_config.ranking.sigma
        )

    async def login(
        self,
        login_schema: LoginUserSchema
    ) -> tuple[str, str]:

        await self.anti_spam.increment_ip_attempts()
        await self.anti_spam.check_login_lock(login_schema.email)

        user = await self.ur.get_by_auth(login_schema.email, login_schema.password)
        if user is None:
            await self.redis.set(f"{RedisType.incorrect_credentials.value}:{login_schema.email}", 0,
                                 ex=Config.login_gap)
            raise UserNotFoundException()

        access = AccessToken(user=user).to_token()
        refresh = RefreshToken(
            user_id=user.id, secret=user.secret).to_token()
        return access, refresh

    async def refresh(
        self,
        refresh_token: str | None,
    ) -> str:
        if refresh_token is None:
            raise RefreshTokenMissingException()

        refresh = RefreshToken.from_token(refresh_token)
        now = datetime.now(UTC).replace(tzinfo=None)

        if refresh.created_date > now or refresh.created_date + refresh.lifetime < now:
            raise RefreshTokenExpiredException()

        user = await self.ur.get_by_id(refresh.user_id)
        if not user or user.secret != refresh.secret:
            raise RefreshTokenInvalidException()

        access = AccessToken(user, now).to_token()
        return access

    async def logout(
        self,
        user: User
    ) -> None:
        await self.ur.update_secret(user)
