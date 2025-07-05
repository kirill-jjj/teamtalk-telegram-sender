from typing import Callable, Coroutine, Any, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.orm import sessionmaker

class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, session_factory: sessionmaker): # type: ignore
        super().__init__()
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Coroutine[Any, Any, Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.session_factory() as session:
            data["session"] = session
            return await handler(event, data)
