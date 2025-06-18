from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession # Keep for type hint, may not be used
from bot.state import ADMIN_IDS_CACHE # Import new cache

class IsAdminFilter(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery, session: AsyncSession) -> bool:
        # session parameter is kept for now to maintain consistent filter signature,
        # though it's not used by this simplified cache-only check.
        user_obj = event.from_user
        if not user_obj:
            return False

        user_id = user_obj.id
        return user_id in ADMIN_IDS_CACHE
