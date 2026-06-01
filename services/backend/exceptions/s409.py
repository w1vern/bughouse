
from .base import BaseConflictException


class UserAlreadyExistsException(BaseConflictException):
    def __init__(self) -> None:
        super().__init__(detail="User with email or username already exists.")


class OAuthAccountAlreadyLinkedException(BaseConflictException):
    def __init__(self) -> None:
        super().__init__(detail="This provider account is already linked to a user")

