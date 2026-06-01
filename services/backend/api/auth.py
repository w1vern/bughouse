
from fastapi import APIRouter, Cookie, Depends, Response
from fastapi.responses import RedirectResponse

from shared.database import User

from ..config import SECURE_COOKIES, Config
from ..depends import get_db_user, get_user
from ..response import SuccessResponse
from ..schemas import (
    CreateUserSchema,
    LoginUserSchema,
    OAuthCompleteSchema,
    OAuthLinkSchema,
    OAuthProviderSchema,
    OAuthRegistrationSchema,
    UserTokenSchema
)
from ..services import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_access_cookie(response: Response, access: str) -> None:
    response.set_cookie(
        key="access_token",
        value=access,
        max_age=Config.access_token_lifetime,
        httponly=True,
        samesite='strict',
        secure=SECURE_COOKIES,
        path="/api"
    )


def _set_refresh_cookie(response: Response, refresh: str) -> None:
    response.set_cookie(
        key="refresh_token",
        value=refresh,
        max_age=Config.refresh_token_lifetime,
        httponly=True,
        samesite='strict',
        secure=SECURE_COOKIES,
        path="/api/auth/refresh"
    )


@router.post(
    path="/refresh",
    summary="Refresh the access token"
)
async def refresh(refresh_token: str | None = Cookie(None),
                  auth_service: AuthService = Depends(AuthService.depends)
                  ) -> SuccessResponse:
    access = await auth_service.refresh(refresh_token)
    response = SuccessResponse()
    _set_access_cookie(response, access)
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
    _set_refresh_cookie(response, refresh)
    _set_access_cookie(response, access)
    return response


@router.get(
    path="/oauth/providers",
    summary="List available third-party login providers"
)
async def oauth_providers(
    auth_service: AuthService = Depends(AuthService.depends)
) -> list[OAuthProviderSchema]:
    return auth_service.list_providers()


@router.get(
    path="/oauth/{provider}/login",
    summary="Start login via a third-party provider"
)
async def oauth_login(provider: str,
                      auth_service: AuthService = Depends(AuthService.depends)
                      ) -> RedirectResponse:
    url = await auth_service.oauth_start(provider, "authenticate")
    return RedirectResponse(url)


@router.get(
    path="/oauth/{provider}/link",
    summary="Link a third-party provider to the current account"
)
async def oauth_link(provider: str,
                     user: UserTokenSchema = Depends(get_user),
                     auth_service: AuthService = Depends(AuthService.depends)
                     ) -> RedirectResponse:
    url = await auth_service.oauth_start(provider, "link", user.id)
    return RedirectResponse(url)


@router.get(
    path="/oauth/{provider}/callback",
    summary="Third-party provider redirect callback"
)
async def oauth_callback(provider: str,
                         code: str,
                         state: str,
                         auth_service: AuthService = Depends(AuthService.depends)
                         ) -> RedirectResponse:
    result = await auth_service.oauth_callback(provider, code, state)
    response = RedirectResponse(result.redirect_url)
    if result.tokens is not None:
        access, refresh = result.tokens
        _set_refresh_cookie(response, refresh)
        _set_access_cookie(response, access)
    return response


@router.get(
    path="/oauth/registration",
    summary="Get prefilled data for the OAuth registration form"
)
async def oauth_registration(
    token: str,
    auth_service: AuthService = Depends(AuthService.depends)
) -> OAuthRegistrationSchema:
    return auth_service.oauth_registration(token)


@router.post(
    path="/oauth/complete",
    summary="Finish registration started via a third-party provider"
)
async def oauth_complete(
    complete_schema: OAuthCompleteSchema,
    auth_service: AuthService = Depends(AuthService.depends)
) -> SuccessResponse:
    access, refresh = await auth_service.oauth_complete(complete_schema)
    response = SuccessResponse()
    _set_refresh_cookie(response, refresh)
    _set_access_cookie(response, access)
    return response


@router.get(
    path="/oauth/links",
    summary="List providers linked to the current account"
)
async def oauth_links(
    user: User = Depends(get_db_user),
    auth_service: AuthService = Depends(AuthService.depends)
) -> list[OAuthLinkSchema]:
    return await auth_service.oauth_links(user)


@router.delete(
    path="/oauth/links/{provider}",
    summary="Unlink a provider from the current account"
)
async def oauth_unlink(
    provider: str,
    user: User = Depends(get_db_user),
    auth_service: AuthService = Depends(AuthService.depends)
) -> SuccessResponse:
    await auth_service.oauth_unlink(user, provider)
    return SuccessResponse()


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
    await auth_service.logout_all(user)
    response.delete_cookie(
        key="refresh_token",
        path="/api/auth/refresh"
    )
    response.delete_cookie(
        key="access_token",
        path="/api"
    )
    return response
