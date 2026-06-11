
from fastapi import APIRouter

from ..websocket import router as ws_router
from .auth import router as auth_router
from .bot import router as bot_router
from .game import router as game_router
from .stats import router as stats_router
from .user import router as user_router
from .ws_docs import router as ws_docs_router

router = APIRouter(prefix="/api")

router.include_router(auth_router)
router.include_router(user_router)
router.include_router(bot_router)
router.include_router(game_router)
router.include_router(stats_router)
router.include_router(ws_router)
router.include_router(ws_docs_router)

