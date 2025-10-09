"""Service for generating reports."""

from gettext import NullTranslations
import logging
from typing import TYPE_CHECKING

import pytalk

from bot.command_bus.bus import CommandBus
from bot.command_bus.exceptions import NoHandlerFoundError
from bot.commands import GetOnlineUsersCommand, GetOnlineUsersResult
from bot.config import Settings
from bot.constants import USERS_PER_PAGE
from bot.database.uow import IUnitOfWork
from bot.services.cache_service import CacheService
from bot.services.schemas import PaginatedResult, SubscriberInfo
from bot.services.user_settings_service import UserSettingsService
from bot.telegram_bot.api import get_display_names_for_ids
from bot.telegram_bot.models import WhoChannelGroup, WhoReport, WhoUser
from bot.telegram_bot.types.bots import EventBot

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


class ReportService:
    """Service for generating reports."""

    def __init__(
        self,
        settings: Settings,
        uow: IUnitOfWork,
        bot: EventBot,
    ) -> None:
        """Initializes the report service."""
        self._settings = settings
        self._uow = uow
        self._bot = bot

    async def get_who_report_data(
        self,
        telegram_user_id: int,
        translator: NullTranslations,
        cache_service: CacheService,
        user_settings_service: UserSettingsService,
        command_bus: CommandBus,
    ) -> WhoReport | str:
        """Gather online user data and return a structured report or an error string."""
        _ = translator.gettext
        user_settings = await user_settings_service.get_or_create(
            telegram_user_id, self._settings.general.default_lang
        )
        is_admin = cache_service.is_admin(telegram_user_id)
        command = GetOnlineUsersCommand(
            is_caller_admin=is_admin, lang_code=user_settings.language_code
        )

        try:
            result: GetOnlineUsersResult = await command_bus.execute(command)
        except NoHandlerFoundError:
            logger.critical("CRITICAL: No handler for GetOnlineUsersCommand!")
            return _("This feature is temporarily unavailable.")

        if not result.success or not result.users:
            return result.error_message or _("No users found online.")

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

        return WhoReport(
            server_name=result.server_name,
            total_users=user_count,
            grouped_data=grouped_data,
        )

    def get_help_text(self, translator: NullTranslations, *, is_admin: bool) -> str:
        """Builds the help message for Telegram users."""
        _ = translator.gettext
        parts = [
            _("<b>Available Commands:</b>"),
            _(
                "/who - Show online users.\n"
                "/settings - Access the interactive settings menu "
                "(language, notifications, mute lists, NOON feature).\n"
                "/help - Show this help message.\n"
                "(Note: `/start` is used to initiate the bot and process deeplinks.)"
            ),
        ]
        if is_admin:
            parts.extend(
                [
                    _("\n<b>Admin Commands:</b>"),
                    _(
                        "/kick - Kick a user from the server (via buttons).\n"
                        "/ban - Ban a user from the server (via buttons).\n"
                        "/unban - Unban a user from the server "
                        "(shows a list of banned users).\n"
                        "/subscribers - View and manage subscribed users."
                    ),
                ]
            )
        return "\n".join(parts)

    async def get_subscribers_info(self, page: int) -> PaginatedResult[SubscriberInfo]:
        """Fetches and prepares a paginated list of subscribers."""
        async with self._uow:
            offset = page * USERS_PER_PAGE
            total_items = await self._uow.subscribers.count_all()
            subscribers = await self._uow.subscribers.get_paginated(
                offset, USERS_PER_PAGE
            )

            subscriber_ids = [sub.telegram_id for sub in subscribers]
            user_settings_list = await self._uow.users.get_by_ids(subscriber_ids)
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
                        teamtalk_username=settings.teamtalk_username
                        if settings
                        else None,
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

    async def get_banned_users_info(self, page: int) -> PaginatedResult[SubscriberInfo]:
        """Fetches and prepares a paginated list of banned users."""
        async with self._uow:
            offset = page * USERS_PER_PAGE
            total_items = await self._uow.bans.count_with_telegram_id()
            banned_entries = await self._uow.bans.get_paginated_with_telegram_id(
                offset, USERS_PER_PAGE
            )

            banned_ids = [
                entry.telegram_id for entry in banned_entries if entry.telegram_id
            ]
            user_settings_list = await self._uow.users.get_by_ids(banned_ids)
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
