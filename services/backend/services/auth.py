
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from secrets import token_urlsafe
from urllib.parse import urlencode
from uuid import UUID

from fastapi import Depends
from redis.asyncio import Redis

from shared.database import (
    AuthProviderRepository,
    User,
    UserRepository
)
from shared.infrastructure import env_config

from ..config import Config
from ..depends import get_auth_provider_repo, get_user_repo
from ..exceptions import *
from ..oauth import (
    OAuthIdentity,
    available_providers,
    generate_pkce_pair,
    get_client,
    oauth_redirect_uri
)
from ..redis import RedisType, get_redis_client
from ..schemas import (
    CreateUserSchema,
    LoginUserSchema,
    OAuthCompleteSchema,
    OAuthLinkSchema,
    OAuthProviderSchema,
    OAuthRegistrationSchema
)
from ..token import AccessToken, OAuthRegistrationToken, RefreshToken

OAUTH_INTENT_AUTHENTICATE = "authenticate"
OAUTH_INTENT_LINK = "link"


@dataclass
class OAuthAuthResult:
    # Outcome of resolving an identity into a session: either the user is
    # logged in (tokens) or a new account must finish registration (token).
    tokens: tuple[str, str] | None = None
    registration_token: str | None = None


@dataclass
class OAuthCallbackResult:
    redirect_url: str
    tokens: tuple[str, str] | None = None


class AuthService:
    def __init__(
        self,
        ur: UserRepository,
        apr: AuthProviderRepository,
        redis: Redis,
    ) -> None:
        self.ur = ur
        self.apr = apr
        self.redis = redis

    @classmethod
    def depends(
        cls,
        ur: UserRepository = Depends(get_user_repo),
        apr: AuthProviderRepository = Depends(get_auth_provider_repo),
        redis: Redis = Depends(get_redis_client),
    ) -> 'AuthService':
        return cls(ur, apr, redis)

    def _issue_tokens(
        self,
        user: User
    ) -> tuple[str, str]:
        access = AccessToken(user=user).to_token()
        refresh = RefreshToken(
            user_id=user.id, secret=user.secret).to_token()
        return access, refresh

    async def register(
        self,
        register_schema: CreateUserSchema
    ) -> None:
        if register_schema.password != register_schema.repeat_password:
            raise PasswordsDoNotMatchException()
        try:
            await self.ur.create(
                email=register_schema.email,
                username=register_schema.username,
                password=register_schema.password,
                rating=env_config.ranking.mu,
                sigma=env_config.ranking.sigma,
                color=0
            )
        except Exception:
            raise UserAlreadyExistsException()

    async def login(
        self,
        login_schema: LoginUserSchema
    ) -> tuple[str, str]:
        user = await self.ur.get_by_auth(login_schema.email, login_schema.password)
        if user is None:
            raise UserNotFoundException()
        return self._issue_tokens(user)

    def list_providers(self) -> list[OAuthProviderSchema]:
        return [
            OAuthProviderSchema(
                key=config.key,
                display_name=config.display_name,
                icon_url=config.icon_url,
                color=config.color
            )
            for config in available_providers()
        ]

    async def oauth_start(
        self,
        provider: str,
        intent: str,
        user_id: UUID | None = None
    ) -> str:
        client = get_client(provider)
        state = token_urlsafe()
        payload: dict[str, str] = {"provider": provider, "intent": intent}
        if user_id is not None:
            payload["user_id"] = str(user_id)
        code_challenge = None
        if client.config.pkce:
            verifier, code_challenge = generate_pkce_pair()
            payload["code_verifier"] = verifier
        await self.redis.set(
            f"{RedisType.oauth_state.value}:{state}",
            json.dumps(payload),
            ex=Config.oauth_state_lifetime
        )
        return client.build_authorize_url(
            oauth_redirect_uri(provider), state, code_challenge)

    async def oauth_callback(
        self,
        provider: str,
        code: str,
        state: str
    ) -> OAuthCallbackResult:
        client = get_client(provider)
        key = f"{RedisType.oauth_state.value}:{state}"
        raw = await self.redis.get(key)
        if raw is None:
            raise OAuthStateInvalidException()
        await self.redis.delete(key)
        payload = json.loads(raw)
        if payload.get("provider") != provider:
            raise OAuthStateInvalidException()
        identity = await client.fetch_identity(
            code, oauth_redirect_uri(provider), payload.get("code_verifier"))
        if payload.get("intent") == OAUTH_INTENT_LINK:
            raw_user_id = payload.get("user_id")
            if raw_user_id is None:
                raise OAuthStateInvalidException()
            await self._link_identity(identity, UUID(raw_user_id))
            return OAuthCallbackResult(redirect_url=env_config.frontend_url)
        result = await self._authenticate_identity(identity)
        if result.tokens is not None:
            return OAuthCallbackResult(
                redirect_url=env_config.frontend_url,
                tokens=result.tokens
            )
        query = urlencode({"token": result.registration_token})
        return OAuthCallbackResult(
            redirect_url=f"{env_config.frontend_url}/oauth/complete?{query}"
        )

    async def _authenticate_identity(
        self,
        identity: OAuthIdentity
    ) -> OAuthAuthResult:
        link = await self.apr.get_by_account(
            identity.provider, identity.provider_user_id)
        if link is not None:
            return OAuthAuthResult(tokens=self._issue_tokens(link.user))
        if identity.email is not None and identity.email_verified:
            user = await self.ur.get_by_email(identity.email)
            if user is not None:
                await self.apr.create(
                    provider=identity.provider,
                    provider_user_id=identity.provider_user_id,
                    user_id=user.id
                )
                return OAuthAuthResult(tokens=self._issue_tokens(user))
        token = OAuthRegistrationToken(
            provider=identity.provider,
            provider_user_id=identity.provider_user_id,
            username=identity.username,
            email=identity.email,
            avatar_url=identity.avatar_url
        ).to_token()
        return OAuthAuthResult(registration_token=token)

    async def _link_identity(
        self,
        identity: OAuthIdentity,
        user_id: UUID
    ) -> None:
        existing = await self.apr.get_by_account(
            identity.provider, identity.provider_user_id)
        if existing is not None:
            if existing.user_id != user_id:
                raise OAuthAccountAlreadyLinkedException()
            return
        await self.apr.create(
            provider=identity.provider,
            provider_user_id=identity.provider_user_id,
            user_id=user_id
        )

    def _decode_registration(
        self,
        token: str
    ) -> OAuthRegistrationToken:
        try:
            registration = OAuthRegistrationToken.from_token(token)
        except Exception:
            raise OAuthRegistrationTokenInvalidException()
        now = datetime.now(UTC).replace(tzinfo=None)
        if registration.created_date > now or \
                registration.created_date + registration.lifetime < now:
            raise OAuthRegistrationTokenInvalidException()
        return registration

    def oauth_registration(
        self,
        token: str
    ) -> OAuthRegistrationSchema:
        registration = self._decode_registration(token)
        return OAuthRegistrationSchema(
            provider=registration.provider,
            email=registration.email,
            username=registration.username,
            avatar_url=registration.avatar_url
        )

    async def oauth_complete(
        self,
        complete_schema: OAuthCompleteSchema
    ) -> tuple[str, str]:
        registration = self._decode_registration(complete_schema.token)
        if complete_schema.password != complete_schema.repeat_password:
            raise PasswordsDoNotMatchException()
        existing = await self.apr.get_by_account(
            registration.provider, registration.provider_user_id)
        if existing is not None:
            raise OAuthAccountAlreadyLinkedException()
        try:
            user = await self.ur.create(
                email=complete_schema.email,
                username=complete_schema.username,
                password=complete_schema.password,
                rating=env_config.ranking.mu,
                sigma=env_config.ranking.sigma,
                color=0
            )
        except Exception:
            raise UserAlreadyExistsException()
        await self.apr.create(
            provider=registration.provider,
            provider_user_id=registration.provider_user_id,
            user_id=user.id
        )
        return self._issue_tokens(user)

    async def oauth_links(
        self,
        user: User
    ) -> list[OAuthLinkSchema]:
        links = await self.apr.get_all(user_id=user.id)
        return [
            OAuthLinkSchema(provider=link.provider,
                            created_date=link.created_date)
            for link in links
        ]

    async def oauth_unlink(
        self,
        user: User,
        provider: str
    ) -> None:
        links = await self.apr.get_all(user_id=user.id, provider=provider)
        if not links:
            raise OAuthLinkNotFoundException(provider)
        for link in links:
            await self.apr.delete(link)

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

    async def logout_all(
        self,
        user: User
    ) -> None:
        await self.redis.set(f"{RedisType.invalidated_access_token.value}:{user.id}", 1)
        await self.ur.update_secret(user)
