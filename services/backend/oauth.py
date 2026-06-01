
import base64
import hashlib
from dataclasses import dataclass
from secrets import token_urlsafe
from urllib.parse import urlencode

import httpx

from shared.infrastructure import env_config
from shared.infrastructure.config import OAuthProviderSettings

from .exceptions import (
    OAuthProviderNotConfiguredException,
    OAuthProviderNotSupportedException,
    OAuthTokenExchangeFailedException,
    OAuthUserInfoFailedException
)


@dataclass(frozen=True)
class OAuthIdentity:
    provider: str
    provider_user_id: str
    username: str
    email: str | None
    email_verified: bool
    avatar_url: str | None


@dataclass(frozen=True)
class ProviderConfig:
    key: str
    display_name: str
    icon_url: str
    color: str
    pkce: bool = False
    authorize_url: str | None = None
    token_url: str | None = None
    userinfo_url: str | None = None
    scope: str = ""
    id_field: str = ""
    username_field: str = ""
    avatar_field: str | None = None
    email_field: str | None = None
    email_verified_field: str | None = None
    emails_url: str | None = None

    @property
    def requires_secret(self) -> bool:
        # PKCE (public) clients authenticate with a code verifier, not a secret.
        return not self.pkce


# Single source of truth for every provider. Adding a provider is one entry
# here plus its credentials in env.
PROVIDERS: dict[str, ProviderConfig] = {
    "google": ProviderConfig(
        key="google",
        display_name="Google",
        icon_url="https://www.google.com/favicon.ico",
        color="#4285F4",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
        scope="openid email profile",
        id_field="sub",
        username_field="name",
        avatar_field="picture",
        email_field="email",
        email_verified_field="email_verified"
    ),
    "github": ProviderConfig(
        key="github",
        display_name="GitHub",
        icon_url="https://github.githubassets.com/favicons/favicon.png",
        color="#24292F",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        userinfo_url="https://api.github.com/user",
        scope="read:user user:email",
        id_field="id",
        username_field="login",
        avatar_field="avatar_url",
        emails_url="https://api.github.com/user/emails"
    ),
    "lichess": ProviderConfig(
        key="lichess",
        display_name="Lichess",
        icon_url="https://lichess.org/favicon.ico",
        color="#4D4D4D",
        pkce=True,
        authorize_url="https://lichess.org/oauth",
        token_url="https://lichess.org/api/token",
        userinfo_url="https://lichess.org/api/account",
        scope="",
        id_field="id",
        username_field="username"
    )
}


def _credentials(key: str) -> OAuthProviderSettings | None:
    return getattr(env_config.oauth, key, None)


def is_configured(key: str) -> bool:
    config = PROVIDERS.get(key)
    credentials = _credentials(key)
    if config is None or credentials is None or not credentials.id:
        return False
    if config.requires_secret and not credentials.secret:
        return False
    return True


def available_providers() -> list[ProviderConfig]:
    return [config for key, config in PROVIDERS.items() if is_configured(key)]


def generate_pkce_pair() -> tuple[str, str]:
    verifier = token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


class OAuthClient:
    def __init__(
        self,
        config: ProviderConfig,
        client_id: str,
        client_secret: str
    ) -> None:
        self.config = config
        self.client_id = client_id
        self.client_secret = client_secret

    def build_authorize_url(
        self,
        redirect_uri: str,
        state: str,
        code_challenge: str | None = None
    ) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state
        }
        if self.config.scope:
            params["scope"] = self.config.scope
        if code_challenge is not None:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        return f"{self.config.authorize_url}?{urlencode(params)}"

    async def _exchange_code(
        self,
        client: httpx.AsyncClient,
        code: str,
        redirect_uri: str,
        code_verifier: str | None
    ) -> str:
        data = {
            "client_id": self.client_id,
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code"
        }
        if code_verifier is not None:
            data["code_verifier"] = code_verifier
        if self.client_secret:
            data["client_secret"] = self.client_secret
        response = await client.post(
            self.config.token_url,
            data=data,
            headers={"Accept": "application/json"}
        )
        if response.status_code != 200:
            raise OAuthTokenExchangeFailedException()
        access_token = response.json().get("access_token")
        if not access_token:
            raise OAuthTokenExchangeFailedException()
        return access_token

    def _extract_email(
        self,
        data: dict
    ) -> tuple[str | None, bool]:
        if self.config.email_field is None:
            return None, False
        email = data.get(self.config.email_field)
        if email is None:
            return None, False
        if self.config.email_verified_field is None:
            return email, True
        return email, bool(data.get(self.config.email_verified_field))

    async def _fetch_primary_email(
        self,
        client: httpx.AsyncClient,
        headers: dict
    ) -> str | None:
        response = await client.get(self.config.emails_url, headers=headers)
        if response.status_code != 200:
            return None
        return next(
            (item["email"] for item in response.json()
             if item.get("primary") and item.get("verified")),
            None
        )

    async def fetch_identity(
        self,
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None
    ) -> OAuthIdentity:
        async with httpx.AsyncClient() as client:
            access_token = await self._exchange_code(
                client, code, redirect_uri, code_verifier)
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json"
            }
            response = await client.get(self.config.userinfo_url, headers=headers)
            if response.status_code != 200:
                raise OAuthUserInfoFailedException()
            data = response.json()
            email, verified = self._extract_email(data)
            if email is None and self.config.emails_url is not None:
                email = await self._fetch_primary_email(client, headers)
                verified = email is not None
        return OAuthIdentity(
            provider=self.config.key,
            provider_user_id=str(data[self.config.id_field]),
            username=str(data.get(self.config.username_field) or ""),
            email=email,
            email_verified=verified,
            avatar_url=(data.get(self.config.avatar_field)
                        if self.config.avatar_field else None)
        )


def get_client(key: str) -> OAuthClient:
    config = PROVIDERS.get(key)
    if config is None:
        raise OAuthProviderNotSupportedException(key)
    credentials = _credentials(key)
    if credentials is None or not credentials.id or \
            (config.requires_secret and not credentials.secret):
        raise OAuthProviderNotConfiguredException(key)
    return OAuthClient(config, credentials.id, credentials.secret)


def oauth_redirect_uri(key: str) -> str:
    return f"{env_config.base_url}/api/auth/oauth/{key}/callback"
