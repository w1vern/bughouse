
from fastapi import APIRouter

from .auth import router as auth_router
from .game import router as game_router
from .ranking_param import router as ranking_param_router
from .user import router as user_router

router = APIRouter(prefix="/api")

router.include_router(auth_router)
router.include_router(user_router)
router.include_router(game_router)
router.include_router(ranking_param_router)
