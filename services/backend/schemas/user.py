
from uuid import UUID

from pydantic import BaseModel

from shared.database import User


class UserSchema(BaseModel):
    id: UUID
    email: str | None
    username: str
    rating: float
    sigma: float

    @classmethod
    def from_db(cls, user: User) -> "UserSchema":
        return cls(
            id=user.id,
            email=user.email,
            username=user.username,
            rating=user.rating,
            sigma=user.sigma
        )


class CreateUserSchema(BaseModel):
    email: str
    username: str
    password: str
    repeat_password: str


class LoginUserSchema(BaseModel):
    email: str
    password: str


class EditUserSchema(BaseModel):
    email: str | None
    username: str | None
    password: str | None
    repeat_password: str | None
