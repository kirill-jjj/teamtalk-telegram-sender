from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from bot.database.crud import is_admin as db_is_admin # Renamed to avoid conflict

class IsAdminFilter(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery, session: AsyncSession) -> bool:
        user_obj = event.from_user
        if not user_obj:
            return False
        return await db_is_admin(session, user_obj.id)
