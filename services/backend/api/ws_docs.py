from typing import Any

from fastapi import APIRouter

from shared.events.gen import build_schema

router = APIRouter(tags=["WebSocket"])

_SCHEMA_CACHE: dict[str, Any] | None = None


def _schema() -> dict[str, Any]:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        _SCHEMA_CACHE = build_schema()
    return _SCHEMA_CACHE


@router.get(
    path="/ws-docs.json",
    summary="Websocket events JSON schema",
    response_model=None
)
async def ws_docs_json() -> dict[str, Any]:
    return _schema()
