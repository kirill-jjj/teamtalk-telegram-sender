from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession # Keep for type hint, may not be used
from bot.state import ADMIN_IDS_CACHE # Import new cache

class IsAdminFilter(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery, session: AsyncSession) -> bool:
        user_obj = event.from_user
        if not user_obj:
            return False

        user_id = user_obj.id
        return user_id in ADMIN_IDS_CACHE
