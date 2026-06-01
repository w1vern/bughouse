
from .base import BaseBadRequestException


class PasswordsDoNotMatchException(BaseBadRequestException):
    def __init__(self) -> None:
        super().__init__(detail="Password do not match")


class OAuthStateInvalidException(BaseBadRequestException):
    def __init__(self) -> None:
        super().__init__(detail="Invalid or expired OAuth state")


class OAuthRegistrationTokenInvalidException(BaseBadRequestException):
    def __init__(self) -> None:
        super().__init__(detail="Invalid or expired OAuth registration token")
