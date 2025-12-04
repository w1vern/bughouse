
from fastapi import APIRouter, Cookie, Depends

from shared.database import User

from ..config import SECURE_COOKIES, Config
from ..depends import get_db_user
from ..response import SuccessResponse
from ..schemas import CreateUserSchema, LoginUserSchema
from ..services import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    path="/refresh",
    summary="Refresh the access token"
)
async def refresh(refresh_token: str | None = Cookie(None),
                  auth_service: AuthService = Depends(AuthService.depends)
                  ) -> SuccessResponse:
    access = await auth_service.refresh(refresh_token)
    response = SuccessResponse()
    response.set_cookie(
        key="access_token",
        value=access,
        max_age=Config.access_token_lifetime,
        httponly=True,
        samesite='strict',
        secure=SECURE_COOKIES,
        path="/api"
    )
    return response


@router.post(
    path="/login",
    summary="Login using Telegram authentication"
)
async def login(login_schema: LoginUserSchema,
                auth_service: AuthService = Depends(AuthService.depends)
                ) -> SuccessResponse:
    access, refresh = await auth_service.login(login_schema)
    response = SuccessResponse()
    response.set_cookie(
        key="refresh_token",
        value=refresh,
        max_age=Config.refresh_token_lifetime,
        httponly=True, samesite='strict',
        secure=SECURE_COOKIES,
        path="/api/auth/refresh"
    )
    response.set_cookie(
        key="access_token",
        value=access,
        max_age=Config.access_token_lifetime,
        httponly=True,
        samesite='strict',
        secure=SECURE_COOKIES,
        path="/api"
    )
    return response


@router.post(
    path="/register",
    summary=""
)
async def register(register_schema: CreateUserSchema,
                   auth_service: AuthService = Depends(AuthService.depends)
                   ) -> SuccessResponse:
    await auth_service.register(register_schema)
    return SuccessResponse()


@router.post(
    path="/logout",
    summary="Logout the admin"
)
async def logout() -> SuccessResponse:
    response = SuccessResponse()
    response.delete_cookie(
        key="refresh_token",
        path="/api/auth/refresh"
    )
    response.delete_cookie(
        key="access_token",
        path="/api"
    )
    return response


@router.post(
    path="/logout_all",
    summary="Logout the admin from all devices"
)
async def logout_all(
    user: User = Depends(get_db_user),
    auth_service: AuthService = Depends(AuthService.depends)
) -> SuccessResponse:
    response = SuccessResponse()
    await auth_service.logout(user)
    response.delete_cookie(
        key="refresh_token",
        path="/api/auth/refresh"
    )
    response.delete_cookie(
        key="access_token",
        path="/api"
    )
    return response
