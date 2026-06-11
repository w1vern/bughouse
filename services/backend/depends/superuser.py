
from fastapi import Depends

from shared.infrastructure import env_config

from ..exceptions import PermissionDeniedException
from ..schemas import UserTokenSchema
from .user import get_user


async def get_superuser(
    user: UserTokenSchema = Depends(get_user)
) -> UserTokenSchema:
    if user.username != env_config.superuser.username:
        raise PermissionDeniedException()
    return user
