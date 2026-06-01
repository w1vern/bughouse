
from datetime import datetime

from pydantic import BaseModel


class OAuthProviderSchema(BaseModel):
    key: str
    display_name: str
    icon_url: str
    color: str


class OAuthRegistrationSchema(BaseModel):
    provider: str
    email: str | None
    username: str
    avatar_url: str | None


class OAuthCompleteSchema(BaseModel):
    token: str
    email: str
    username: str
    password: str
    repeat_password: str


class OAuthLinkSchema(BaseModel):
    provider: str
    created_date: datetime
