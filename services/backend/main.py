
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api import router
from .response import SuccessResponse
from .websocket.grpc_client import close_grpc_channel, init_grpc_channel


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await init_grpc_channel()
    try:
        yield
    finally:
        await close_grpc_channel()


app = FastAPI(
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    swagger_ui_parameters={
        "tryItOutEnabled": True,
    },
    lifespan=lifespan,
)


@router.get("/health", include_in_schema=False)
async def health() -> SuccessResponse:
    return SuccessResponse()


app.include_router(router)
