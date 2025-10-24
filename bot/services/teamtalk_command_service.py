"""Service for handling commands received from TeamTalk."""

from gettext import NullTranslations

from bot.config import Settings
from bot.core.enums import DeeplinkAction
from bot.database.uow import IUnitOfWork
from bot.services import schemas
from bot.services.admin_service import AdminService
from bot.services.cache_service import CacheService
from bot.services.deeplink_service import DeeplinkService
from bot.services.schemas import AdminManagementResult
from bot.teamtalk_bot.formatters import format_deeplink_reply


class TeamTalkCommandService:
    """Service for handling commands received from TeamTalk private messages."""

    def __init__(
        self,
        settings: Settings,
        cache: CacheService,
        deeplink_service: DeeplinkService,
        admin_service: AdminService,
    ) -> None:
        """Initializes the TeamTalk command service."""
        self.settings = settings
        self.cache = cache
        self.deeplink_service = deeplink_service
        self.admin_service = admin_service

    async def handle_subscribe(
        self, uow: IUnitOfWork, tt_username: str, translator: NullTranslations
    ) -> str:
        """Handles the subscribe command logic."""
        deeplink_model = await self.deeplink_service.create_deeplink(
            uow,
            action=DeeplinkAction.SUBSCRIBE,
            ttl_seconds=self.settings.operational_parameters.deeplink_ttl_seconds,
            payload=tt_username,
        )
        bot_username = self.cache.get_bot_username()
        if not bot_username:
            return translator.gettext(
                "Could not generate a link, bot username is not configured."
            )
        return format_deeplink_reply(deeplink_model, bot_username, translator)

    async def handle_unsubscribe(
        self, uow: IUnitOfWork, translator: NullTranslations
    ) -> str:
        """Handles the unsubscribe command logic."""
        deeplink_model = await self.deeplink_service.create_deeplink(
            uow,
            action=DeeplinkAction.UNSUBSCRIBE,
            ttl_seconds=self.settings.operational_parameters.deeplink_ttl_seconds,
        )
        bot_username = self.cache.get_bot_username()
        if not bot_username:
            return translator.gettext(
                "Could not generate a link, bot username is not configured."
            )
        return format_deeplink_reply(deeplink_model, bot_username, translator)

    async def handle_admin_update(
        self,
        uow: IUnitOfWork,
        args_str: str | None,
        translator: NullTranslations,
        *,
        is_add_action: bool,
    ) -> AdminManagementResult:
        """Handles adding or removing admins."""
        _ = translator.gettext
        if not args_str:
            return AdminManagementResult(
                add_result=schemas.BatchOperationResult(),
                remove_result=schemas.BatchOperationResult(),
                error_messages=[_("Please provide Telegram IDs.")],
            )

        add_ids, remove_ids, error_messages = self._parse_admin_ids_args(
            args_str, translator
        )

        return await self.admin_service.apply_admin_changes(
            uow,
            add_ids=add_ids,
            remove_ids=remove_ids,
            is_add_action=is_add_action,
            error_messages=error_messages,
        )

    @staticmethod
    def _parse_admin_ids_args(
        args_string: str, translator: NullTranslations
    ) -> tuple[list[int], list[int], list[str]]:
        _ = translator.gettext
        add_ids = []
        remove_ids = []
        error_messages = []

        args = args_string.split()
        for arg in args:
            if arg.startswith("-"):
                try:
                    remove_ids.append(int(arg[1:]))
                except ValueError:
                    error_messages.append(
                        _("Invalid Telegram ID to remove: {}").format(arg[1:])
                    )
            else:
                try:
                    add_ids.append(int(arg))
                except ValueError:
                    error_messages.append(
                        _("Invalid Telegram ID to add: {}").format(arg)
                    )
        return add_ids, remove_ids, error_messages
