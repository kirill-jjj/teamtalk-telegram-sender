import time # <-- New import
from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from bot.database.crud import is_admin as db_is_admin
from bot.state import ADMIN_RIGHTS_CACHE, ADMIN_CACHE_TTL_SECONDS # <-- New imports

class IsAdminFilter(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery, session: AsyncSession) -> bool:
        user_obj = event.from_user
        if not user_obj:
            return False

        user_id = user_obj.id
        current_time = time.time()

        # 1. Check cache
        cached_data = ADMIN_RIGHTS_CACHE.get(user_id)
        if cached_data:
            is_admin_status, last_check_time = cached_data
            if current_time - last_check_time < ADMIN_CACHE_TTL_SECONDS:
                return is_admin_status # Return fresh result from cache

        # 2. If not in cache or record is stale - go to DB
        is_admin_status = await db_is_admin(session, user_id)

        # 3. Update cache
        ADMIN_RIGHTS_CACHE[user_id] = (is_admin_status, current_time)

        return is_admin_status
