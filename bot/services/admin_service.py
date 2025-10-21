"""Service for managing bot administrators."""

from collections.abc import Callable
from gettext import NullTranslations
import logging

from bot.config import Settings
from bot.database.uow import IUnitOfWork
from bot.event_bus.bus import EventBus
from bot.models import Admin
from bot.services.cache_service import CacheService
from bot.services.schemas import AdminManagementResult, BatchOperationResult
from bot.teamtalk_bot.events import AdminStatusChangedEvent
from bot.telegram_bot.commands import update_user_bot_commands
from bot.telegram_bot.types.bots import EventBot

logger = logging.getLogger(__name__)


class AdminService:
    """Service for managing bot administrators."""

    def __init__(
        self,
        uow: IUnitOfWork,
        cache: CacheService,
        event_bus: EventBus,
        settings: Settings,
    ) -> None:
        """Initializes the admin service."""
        self._uow = uow
        self._cache = cache
        self._event_bus = event_bus
        self._settings = settings

    def is_main_teamtalk_admin(self, username: str) -> bool:
        """Checks if a TeamTalk username matches the configured main admin."""
        admin_username = self._settings.general.admin_username
        if not admin_username:
            return False
        return username == admin_username

    async def add_admin(self, uow: IUnitOfWork, telegram_id: int) -> bool:
        """Adds a new admin, updating DB, cache, and publishing an event."""
        if await uow.admins.get_by_id(telegram_id):
            return False  # Already an admin

        await uow.admins.add(Admin(telegram_id=telegram_id))
        self._cache.add_admin(telegram_id)

        user_settings = await uow.users.get_by_id(telegram_id)
        await self._event_bus.publish(
            AdminStatusChangedEvent(
                telegram_id=telegram_id,
                is_admin=True,
                lang_code=user_settings.language_code if user_settings else None,
            )
        )
        return True

    async def remove_admin(self, uow: IUnitOfWork, telegram_id: int) -> bool:
        """Removes an admin, updating DB, cache, and publishing an event."""
        admin = await uow.admins.get_by_id(telegram_id)
        if not admin:
            return False  # Not an admin

        await uow.admins.delete(admin)
        self._cache.remove_admin(telegram_id)

        user_settings = await uow.users.get_by_id(telegram_id)
        await self._event_bus.publish(
            AdminStatusChangedEvent(
                telegram_id=telegram_id,
                is_admin=False,
                lang_code=user_settings.language_code if user_settings else None,
            )
        )
        return True

    async def add_admins_in_batch(
        self,
        uow: IUnitOfWork,
        telegram_ids: list[int],
    ) -> BatchOperationResult:
        """Adds multiple admins in a batch, returning successful and failed IDs."""
        result = BatchOperationResult()
        for telegram_id in telegram_ids:
            try:
                if await self.add_admin(uow, telegram_id):
                    result.successful_ids.append(telegram_id)
                else:
                    result.failed_ids.append(telegram_id)
            except Exception:
                logger.exception("Failed to add admin %s in batch", telegram_id)
                result.failed_ids.append(telegram_id)
        return result

    async def remove_admins_in_batch(
        self,
        uow: IUnitOfWork,
        telegram_ids: list[int],
    ) -> BatchOperationResult:
        """Removes multiple admins in a batch, returning successful and failed IDs."""
        result = BatchOperationResult()
        for telegram_id in telegram_ids:
            try:
                if await self.remove_admin(uow, telegram_id):
                    result.successful_ids.append(telegram_id)
                else:
                    result.failed_ids.append(telegram_id)
            except Exception:
                logger.exception("Failed to remove admin %s in batch", telegram_id)
                result.failed_ids.append(telegram_id)
        return result

    async def manage_admin_ids(
        self,
        uow: IUnitOfWork,
        add_ids: list[int],
        remove_ids: list[int],
        *,
        is_add_action: bool,
        error_messages: list[str],
    ) -> AdminManagementResult:
        """Processes admin ID management commands and returns a structured result."""
        if is_add_action:
            add_result = await self.add_admins_in_batch(uow, add_ids)
            remove_result = await self.remove_admins_in_batch(uow, remove_ids)
        else:
            add_result = BatchOperationResult()  # No additions
            remove_result = await self.remove_admins_in_batch(uow, add_ids + remove_ids)

        return AdminManagementResult(
            add_result=add_result,
            remove_result=remove_result,
            error_messages=error_messages,
        )

    async def process_admin_management_command(
        self,
        uow: IUnitOfWork,
        add_ids: list[int],
        remove_ids: list[int],
        *,
        is_add_action: bool,
        error_messages: list[str],
    ) -> AdminManagementResult:
        """Processes admin ID management commands.

        Args:
            uow: The unit of work.
            add_ids: List of Telegram IDs to add as admins.
            remove_ids: List of Telegram IDs to remove as admins.
            is_add_action: True if the command is to add admins, False to remove.
            error_messages: List of error messages encountered during parsing.

        Returns:
            An AdminManagementResult containing the outcome of the operation.
        """
        return await self.manage_admin_ids(
            uow,
            add_ids=add_ids,
            remove_ids=remove_ids,
            is_add_action=is_add_action,
            error_messages=error_messages,
        )

    async def ensure_main_admin_exists(
        self,
        uow: IUnitOfWork,
        bot: EventBot,
        translator_factory: Callable[[str], NullTranslations],
    ) -> None:
        """Ensures the main admin from config exists and has correct settings."""
        tg_admin_chat_id = self._settings.telegram.admin_chat_id
        if not tg_admin_chat_id:
            return

        is_newly_created = False
        if not await uow.admins.get_by_id(tg_admin_chat_id):
            await uow.admins.add(Admin(telegram_id=tg_admin_chat_id))
            is_newly_created = True

        if is_newly_created or not self._cache.is_admin(tg_admin_chat_id):
            self._cache.add_admin(tg_admin_chat_id)
            logger.info("Main admin %s ensured in DB and cache.", tg_admin_chat_id)

        user_settings = await uow.users.get_or_create(
            tg_admin_chat_id,
            defaults={"language_code": self._settings.general.default_lang},
        )

        # This part interacts with Telegram API, so it's outside the DB transaction
        translator = translator_factory(user_settings.language_code)
        await update_user_bot_commands(
            telegram_id=tg_admin_chat_id,
            new_lang_code=user_settings.language_code,
            cache=self._cache,
            bot=bot,
            translator=translator,
        )
