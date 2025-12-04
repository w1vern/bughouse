
from .base import BaseForbiddenException


class PermissionDeniedException(BaseForbiddenException):
    def __init__(self) -> None:
        super().__init__(detail="Permission denied")
