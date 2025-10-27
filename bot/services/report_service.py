"""Service for generating reports."""

from gettext import NullTranslations
import logging

import pytalk

from bot.command_bus.bus import CommandBus
from bot.command_bus.exceptions import NoHandlerFoundError
from bot.config import Settings
from bot.core.commands import (
    GetAllTeamTalkAccountsCommand,
    GetAllTeamTalkAccountsResult,
    GetOnlineUsersCommand,
    GetOnlineUsersResult,
)
from bot.core.constants import USERS_PER_PAGE
from bot.database.models import UserSettings
from bot.database.types import MuteListMode
from bot.database.uow import IUnitOfWork
from bot.services.cache_service import CacheService
from bot.services.schemas import (
    AllAccountsViewData,
    ModerationViewData,
    MuteListViewData,
    PaginatedResult,
    SubscriberInfo,
)
from bot.services.user_settings_service import UserSettingsService
from bot.telegram_bot.api import get_display_names_for_ids
from bot.telegram_bot.models import (
    WhoChannelGroup,
    WhoReport,
    WhoReportPayload,
    WhoUser,
)
from bot.telegram_bot.types.bots import EventBot

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


class ReportService:
    """Service for generating reports."""

    def __init__(
        self,
        settings: Settings,
        uow: IUnitOfWork,
        bot: EventBot,
        command_bus: CommandBus,
    ) -> None:
        """Initializes the report service."""
        self._settings = settings
        self._uow = uow
        self._bot = bot
        self._command_bus = command_bus

    async def get_who_report_data(
        self,
        uow: IUnitOfWork,
        telegram_user_id: int,
        translator: NullTranslations,
        cache_service: CacheService,
        user_settings_service: UserSettingsService,
        command_bus: CommandBus,
    ) -> WhoReport:
        """Gathers online user data and returns a structured report DTO."""
        _ = translator.gettext
        user_settings = await user_settings_service.get_or_create(
            uow, telegram_user_id, self._settings.general.default_lang
        )
        is_admin = cache_service.is_admin(telegram_user_id)
        command = GetOnlineUsersCommand(
            is_caller_admin=is_admin, lang_code=user_settings.language_code
        )

        try:
            result: GetOnlineUsersResult = await command_bus.execute(command)
        except NoHandlerFoundError:
            logger.critical("CRITICAL: No handler for GetOnlineUsersCommand!")
            return WhoReport(
                error_message=_("This feature is temporarily unavailable.")
            )

        if not result.success or not result.users:
            return WhoReport(
                error_message=result.error_message or _("No users found online.")
            )

        # Grouping logic is now part of the service
        channels_data: dict[str, list[str]] = {}
        for user in result.users:
            channel_name = user.channel_name
            if channel_name not in channels_data:
                channels_data[channel_name] = []
            channels_data[channel_name].append(user.nickname)

        user_count = len(result.users)

        grouped_data = [
            WhoChannelGroup(
                channel_name=name, users=[WhoUser(nickname=nick) for nick in nicks]
            )
            for name, nicks in channels_data.items()
        ]

        report_payload = WhoReportPayload(
            server_name=result.server_name,
            total_users=user_count,
            grouped_data=grouped_data,
        )
        return WhoReport(payload=report_payload)

    async def get_subscribers_info(
        self, uow: IUnitOfWork, page: int
    ) -> PaginatedResult[SubscriberInfo]:
        """Fetches and prepares a paginated list of subscribers."""
        offset = page * USERS_PER_PAGE
        total_items = await uow.subscribers.count_all()
        subscribers = await uow.subscribers.get_paginated(offset, USERS_PER_PAGE)

        subscriber_ids = [sub.telegram_id for sub in subscribers]
        user_settings_list = await uow.users.get_by_ids(subscriber_ids)
        display_names = await get_display_names_for_ids(self._bot, subscriber_ids)

        user_settings_map = {us.telegram_id: us for us in user_settings_list}

        subscriber_infos = []
        for sub in subscribers:
            settings = user_settings_map.get(sub.telegram_id)
            subscriber_infos.append(
                SubscriberInfo(
                    telegram_id=sub.telegram_id,
                    display_name=display_names.get(
                        sub.telegram_id, str(sub.telegram_id)
                    ),
                    teamtalk_username=(
                        settings.teamtalk_username if settings else None
                    ),
                )
            )

        subscriber_infos.sort(key=lambda user: user.display_name.lower())

        total_pages = (
            (total_items + USERS_PER_PAGE - 1) // USERS_PER_PAGE
            if total_items > 0
            else 1
        )

        return PaginatedResult(
            items=subscriber_infos,
            total_items=total_items,
            total_pages=total_pages,
            current_page=page,
        )

    async def get_banned_users_info(
        self, uow: IUnitOfWork, page: int
    ) -> PaginatedResult[SubscriberInfo]:
        """Fetches and prepares a paginated list of banned users."""
        offset = page * USERS_PER_PAGE
        total_items = await uow.bans.count_with_telegram_id()
        banned_entries = await uow.bans.get_paginated_with_telegram_id(
            offset, USERS_PER_PAGE
        )

        banned_ids = [
            entry.telegram_id for entry in banned_entries if entry.telegram_id
        ]
        user_settings_list = await uow.users.get_by_ids(banned_ids)
        display_names = await get_display_names_for_ids(self._bot, banned_ids)

        user_settings_map = {us.telegram_id: us for us in user_settings_list}

        banned_infos = []
        for entry in banned_entries:
            if entry.telegram_id is None:
                continue
            settings = user_settings_map.get(entry.telegram_id)
            banned_infos.append(
                SubscriberInfo(
                    telegram_id=entry.telegram_id,
                    display_name=display_names.get(
                        entry.telegram_id, str(entry.telegram_id)
                    ),
                    teamtalk_username=(
                        settings.teamtalk_username if settings else None
                    ),
                )
            )

        banned_infos.sort(key=lambda user: user.display_name.lower())

        total_pages = (
            (total_items + USERS_PER_PAGE - 1) // USERS_PER_PAGE
            if total_items > 0
            else 1
        )

        return PaginatedResult(
            items=banned_infos,
            total_items=total_items,
            total_pages=total_pages,
            current_page=page,
        )

    async def get_sorted_online_users_for_moderation(
        self,
        uow: IUnitOfWork,
        telegram_user_id: int,
        translator: NullTranslations,
        cache_service: CacheService,
        user_settings_service: UserSettingsService,
        command_bus: CommandBus,
    ) -> ModerationViewData:
        """Fetches and sorts online users for moderation purposes."""
        _ = translator.gettext
        user_settings = await user_settings_service.get_or_create(
            uow, telegram_user_id, self._settings.general.default_lang
        )
        is_admin = cache_service.is_admin(telegram_user_id)
        command = GetOnlineUsersCommand(
            is_caller_admin=is_admin, lang_code=user_settings.language_code
        )

        try:
            result: GetOnlineUsersResult = await command_bus.execute(command)
        except NoHandlerFoundError:
            logger.critical("CRITICAL: No handler for GetOnlineUsersCommand!")
            return ModerationViewData(
                users=[],
                server_name=self._settings.teamtalk.host_name,
                error_message=_("This feature is temporarily unavailable."),
            )

        if not result.success or not result.users:
            return ModerationViewData(
                users=[],
                server_name=self._settings.teamtalk.host_name,
                error_message=result.error_message or _("No users found online."),
            )

        sorted_users = sorted(result.users, key=lambda u: u.nickname.lower())
        return ModerationViewData(
            users=sorted_users, server_name=self._settings.teamtalk.host_name
        )

    async def get_all_server_accounts_view_data(
        self, lang_code: str, translator: NullTranslations
    ) -> AllAccountsViewData:
        """Fetches and prepares data for the all server accounts list view."""
        _ = translator.gettext
        result: GetAllTeamTalkAccountsResult = await self._command_bus.execute(
            GetAllTeamTalkAccountsCommand(lang_code=lang_code)
        )

        title = _("All Server Accounts")
        empty_text = _("No user accounts found on the server.")

        if not result.success:
            return AllAccountsViewData(
                accounts=[],
                title=title,
                empty_list_text=result.error_message or empty_text,
            )

        sorted_accounts = sorted(result.accounts, key=lambda acc: acc.username.lower())
        return AllAccountsViewData(
            accounts=sorted_accounts, title=title, empty_list_text=empty_text
        )

    def prepare_mute_list_view_data(  # noqa: PLR6301
        self, user_settings: UserSettings, translator: NullTranslations
    ) -> MuteListViewData:
        """Prepares all necessary data for rendering the mute list view."""
        _ = translator.gettext
        items = sorted(
            [muted.muted_teamtalk_username for muted in user_settings.muted_users_list],
            key=str.lower,
        )

        if user_settings.mute_list_mode == MuteListMode.blacklist:
            title = _("Blacklisted Users (Block List)")
            empty_list_text = _("Your blacklist is empty.")
        else:  # Whitelist
            title = _("Whitelisted Users (Allow List)")
            empty_list_text = _("Your whitelist is empty.")

        return MuteListViewData(
            items=items, title=title, empty_list_text=empty_list_text
        )
