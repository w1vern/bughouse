
from uuid import UUID

from fastapi import APIRouter, Depends

from ..schemas import BotSchema, EditBotSchema
from ..services import BotService

router = APIRouter(prefix="/bots", tags=["bots"])


@router.get(
    path="",
    description="List bots (superadmin only)"
)
async def get_all(
    bot_service: BotService = Depends(BotService.depends)
) -> list[BotSchema]:
    return await bot_service.get_all()


@router.patch(
    path="/{id}",
    description="Enable/disable a bot and tune engine settings (superadmin only)"
)
async def update(
    id: UUID,
    edit: EditBotSchema,
    bot_service: BotService = Depends(BotService.depends)
) -> BotSchema:
    return await bot_service.update(id, edit)
