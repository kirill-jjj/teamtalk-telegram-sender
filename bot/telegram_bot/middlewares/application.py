from typing import Callable, Coroutine, Any, Dict, TYPE_CHECKING
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

if TYPE_CHECKING:
    from sender import Application

class ApplicationMiddleware(BaseMiddleware):
    """
    Injects the Application instance into the data of each event.
    """
    def __init__(self, app_instance: "Application"):
        super().__init__()
        self.app_instance = app_instance

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Coroutine[Any, Any, Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        data["app"] = self.app_instance
        return await handler(event, data)
