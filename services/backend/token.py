
from datetime import (
    UTC,
    datetime,
    timedelta,
)
from typing import Any
from uuid import UUID

import jwt

from shared.database import User

from .config import (
    SECRET,
    Config,
)
from .schemas import UserTokenSchema


def decode_jwt(token: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        key=SECRET,
        algorithms=[Config.algorithm])


def encode_jwt(payload: dict[str, Any]) -> str:
    return jwt.encode(
        payload,
        key=SECRET,
        algorithm=Config.algorithm)


class AccessToken:
    def __init__(
        self,
        user: User | UserTokenSchema | dict[str, Any],
        created_date: datetime | str | None = None,
        lifetime: timedelta | float | None = None
    ) -> None:
        if created_date is None:
            self.created_date = datetime.now(UTC).replace(tzinfo=None)
        elif isinstance(created_date, str):
            self.created_date = datetime.fromisoformat(created_date)
        else:
            self.created_date = created_date
        if lifetime is None:
            self.lifetime = timedelta(seconds=Config.access_token_lifetime)
        elif isinstance(lifetime, (float, int)):
            self.lifetime = timedelta(seconds=lifetime)
        else:
            self.lifetime = lifetime
        if isinstance(user, dict):
            self.user = UserTokenSchema(**user)
        elif isinstance(user, User):
            self.user = UserTokenSchema.from_db(user)
        else:
            self.user = user

    @classmethod
    def from_token(cls, token: str) -> "AccessToken":
        return AccessToken(**decode_jwt(token))

    def to_token(self) -> str:
        return encode_jwt({
            "created_date": self.created_date.isoformat(),
            "lifetime": self.lifetime.total_seconds(),
            "user": self.user.model_dump(mode="json")
        })


class RefreshToken:
    def __init__(self,
                 user_id: UUID | str,
                 secret: str,
                 created_date: datetime | str | None = None,
                 lifetime: timedelta | float | None = None
                 ) -> None:
        self.secret = secret
        if created_date is None:
            self.created_date = datetime.now(UTC).replace(tzinfo=None)
        elif isinstance(created_date, str):
            self.created_date = datetime.fromisoformat(created_date)
        else:
            self.created_date = created_date
        if lifetime is None:
            self.lifetime = timedelta(seconds=Config.refresh_token_lifetime)
        elif isinstance(lifetime, (float, int)):
            self.lifetime = timedelta(seconds=lifetime)
        else:
            self.lifetime = lifetime
        if isinstance(user_id, str):
            self.user_id = UUID(user_id)
        else:
            self.user_id = user_id

    @classmethod
    def from_token(cls, token: str) -> "RefreshToken":
        return RefreshToken(**decode_jwt(token))

    def to_token(self) -> str:
        return encode_jwt({
            "created_date": self.created_date.isoformat(),
            "lifetime": self.lifetime.total_seconds(),
            "user_id": str(self.user_id),
            "secret": self.secret
        })


class OAuthRegistrationToken:
    def __init__(self,
                 provider: str,
                 provider_user_id: str,
                 username: str,
                 email: str | None = None,
                 avatar_url: str | None = None,
                 created_date: datetime | str | None = None,
                 lifetime: timedelta | float | None = None
                 ) -> None:
        self.provider = provider
        self.provider_user_id = provider_user_id
        self.username = username
        self.email = email
        self.avatar_url = avatar_url
        if created_date is None:
            self.created_date = datetime.now(UTC).replace(tzinfo=None)
        elif isinstance(created_date, str):
            self.created_date = datetime.fromisoformat(created_date)
        else:
            self.created_date = created_date
        if lifetime is None:
            self.lifetime = timedelta(
                seconds=Config.oauth_registration_token_lifetime)
        elif isinstance(lifetime, (float, int)):
            self.lifetime = timedelta(seconds=lifetime)
        else:
            self.lifetime = lifetime

    @classmethod
    def from_token(cls, token: str) -> "OAuthRegistrationToken":
        return OAuthRegistrationToken(**decode_jwt(token))

    def to_token(self) -> str:
        return encode_jwt({
            "created_date": self.created_date.isoformat(),
            "lifetime": self.lifetime.total_seconds(),
            "provider": self.provider,
            "provider_user_id": self.provider_user_id,
            "username": self.username,
            "email": self.email,
            "avatar_url": self.avatar_url
        })
