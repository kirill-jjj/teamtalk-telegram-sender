from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from dishka import AsyncContainer

from bot.services.cache_service import CacheService


class DishkaInjectMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        container: AsyncContainer = data["dishka_container"]
        data["cache"] = await container.get(CacheService)
        return await handler(event, data)
