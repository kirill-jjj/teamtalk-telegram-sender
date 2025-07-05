# bot/database/engine.py

# Этот файл теперь может быть почти пустым или содержать только
# общие связанные с базой данных утилиты, если они появятся.
# На данный момент, после переноса логики, он может даже не понадобиться.
# Давайте пока оставим его пустым, чтобы не ломать другие импорты.

# В качестве альтернативы, чтобы не удалять файл полностью,
# можно оставить импорты, которые могут использоваться для type hinting.
import logging
from sqlalchemy.ext.asyncio import create_async_engine # noqa
from sqlalchemy.orm import sessionmaker # noqa
from sqlmodel.ext.asyncio.session import AsyncSession # noqa
from bot.constants import DB_MAIN_NAME # noqa
from bot import models  # noqa

logger = logging.getLogger(__name__)

# Весь код создания движка и сессии отсюда УДАЛЯЕМ.
