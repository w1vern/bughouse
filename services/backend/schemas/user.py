
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, StringConstraints

from shared.database import User
from shared.infrastructure import env_config

# Player usernames may only contain lowercase latin letters and digits. This
# also reserves any other character (e.g. capitals) for bot names, so a player
# can never share a username with a bot.
Username = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+$")]


class UserTokenSchema(BaseModel):
    id: UUID
    username: str

    @classmethod
    def from_db(cls, user: User) -> "UserTokenSchema":
        return cls(
            id=user.id,
            username=user.username,
        )


class UserSchema(BaseModel):
    id: UUID
    email: str | None
    username: str
    rating: float
    sigma: float
    is_superadmin: bool

    @classmethod
    def from_db(cls, user: User) -> "UserSchema":
        return cls(
            id=user.id,
            email=user.email,
            username=user.username,
            rating=user.rating,
            sigma=user.sigma,
            is_superadmin=user.username == env_config.superuser.username
        )


class CreateUserSchema(BaseModel):
    email: str
    username: Username
    password: str
    repeat_password: str


class LoginUserSchema(BaseModel):
    email: str
    password: str


class EditUserSchema(BaseModel):
    email: str | None
    username: Username | None
    old_password: str
    password: str | None
    repeat_password: str | None
