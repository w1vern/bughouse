
from .base import BaseBadRequestException


class PasswordsDoNotMatchException(BaseBadRequestException):
    def __init__(self) -> None:
        super().__init__(detail="Password do not match")
