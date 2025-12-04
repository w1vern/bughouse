
from .base import BaseUnauthorizedException


class LoginLockedException(BaseUnauthorizedException):
    def __init__(self, seconds: int) -> None:
        super().__init__(f"Login is locked for {seconds} seconds")


class RequestClientException(BaseUnauthorizedException):
    def __init__(self) -> None:
        super().__init__("Request client not found")


class TooManyAttemptsFromIPException(BaseUnauthorizedException):
    def __init__(self, ip: str) -> None:
        super().__init__(f"Too many incorrect login attempts from IP: {ip}")


class AccessTokenMissingException(BaseUnauthorizedException):
    def __init__(self) -> None:
        super().__init__("Access token is missing")


class AccessTokenExpiredException(BaseUnauthorizedException):
    def __init__(self) -> None:
        super().__init__("Access token has expired")


class AccessTokenInvalidatedException(BaseUnauthorizedException):
    def __init__(self) -> None:
        super().__init__("Access token is invalidated")


class AccessTokenCorruptedException(BaseUnauthorizedException):
    def __init__(self) -> None:
        super().__init__("Access token is corrupted")


class RefreshTokenMissingException(BaseUnauthorizedException):
    def __init__(self) -> None:
        super().__init__("Refresh token is missing")


class RefreshTokenExpiredException(BaseUnauthorizedException):
    def __init__(self) -> None:
        super().__init__("Refresh token has expired")


class RefreshTokenInvalidException(BaseUnauthorizedException):
    def __init__(self) -> None:
        super().__init__("Invalid refresh token")
