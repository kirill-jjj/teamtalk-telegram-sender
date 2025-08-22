"""Service for generating reports."""

from gettext import NullTranslations
from typing import TYPE_CHECKING

from aiogram.utils.formatting import Bold, Text, as_list
import pytalk
from pytalk.user import User as TeamTalkUser

from bot.config import Settings
from bot.constants import (
    USERS_PER_PAGE,
    WHO_CHANNEL_ID_ROOT,
    WHO_CHANNEL_ID_SERVER_ROOT_ALT,
    WHO_CHANNEL_ID_SERVER_ROOT_ALT2,
)
from bot.database.repositories.ban_repository import BanRepository
from bot.database.repositories.subscriber_repository import SubscriberRepository
from bot.database.repositories.user_repository import UserRepository
from bot.services.schemas import PaginatedResult, SubscriberInfo
from bot.telegram_bot.api import get_display_names_for_ids
from bot.telegram_bot.types.bots import EventBot

if TYPE_CHECKING:
    from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.formatters import (
    get_effective_server_name,
    get_tt_user_display_name,
)
from bot.telegram_bot.models import WhoChannelGroup, WhoUser

ttstr = pytalk.instance.sdk.ttstr


def _get_user_display_channel_name(
    user_obj: TeamTalkUser, *, is_caller_admin: bool, translator: "NullTranslations"
) -> str:
    """Gets the display name of the channel a user is in."""
    channel_obj = user_obj.channel
    if not channel_obj:
        return translator.gettext("in unknown location")

    is_channel_hidden = (
        hasattr(pytalk.instance.sdk, "ChannelType")
        and (channel_obj.channel_type & pytalk.instance.sdk.ChannelType.CHANNEL_HIDDEN)
        != 0
    )

    server_root_ids = [
        WHO_CHANNEL_ID_SERVER_ROOT_ALT,
        WHO_CHANNEL_ID_SERVER_ROOT_ALT2,
    ]

    if channel_obj.id in server_root_ids:
        return translator.gettext("under server")

    if is_caller_admin or not is_channel_hidden:
        channel_name = ttstr(channel_obj.name)
        # If the channel name is empty and it's the root channel, use a fallback name
        if not channel_name and channel_obj.id == WHO_CHANNEL_ID_ROOT:
            channel_name = translator.gettext("the root channel")

        return translator.gettext("in {channel_name}").format(channel_name=channel_name)

    return translator.gettext("under server")


def _group_users_for_who_command(
    users: list[TeamTalkUser],
    bot_user_id: int | None,
    *,
    is_caller_admin: bool,
    translator: "NullTranslations",
) -> tuple[list[WhoChannelGroup], int]:
    """Groups users by channel for the /who command output."""
    channels_data: dict[str, list[str]] = {}
    user_count = 0

    for user in users:
        if bot_user_id is not None and user.id == bot_user_id and not is_caller_admin:
            continue

        channel_name = _get_user_display_channel_name(
            user, is_caller_admin=is_caller_admin, translator=translator
        )
        if channel_name not in channels_data:
            channels_data[channel_name] = []

        channels_data[channel_name].append(get_tt_user_display_name(user, translator))
        user_count += 1

    return [
        WhoChannelGroup(
            channel_name=name, users=[WhoUser(nickname=nick) for nick in nicks]
        )
        for name, nicks in channels_data.items()
    ], user_count


def _format_who_message(
    grouped_data: list[WhoChannelGroup],
    total_users: int,
    translator: "NullTranslations",
    server_host: str | None,
) -> str:
    """Formats the final /who message string."""
    _ = translator.gettext
    ngettext = translator.ngettext

    if total_users == 0:
        return (
            _("No users found online on server {server_host}.")
            if server_host
            else _("No users found online.")
        ).format(server_host=server_host)

    header_template = (
        ngettext(
            "There is {user_count} user on the server {server_host}:",
            "There are {user_count} users on the server {server_host}:",
            total_users,
        )
        if server_host
        else ngettext(
            "There is {user_count} user on the server:",
            "There are {user_count} users on the server:",
            total_users,
        )
    )
    header = Text(
        header_template.format(user_count=total_users, server_host=server_host)
    )

    channel_parts = []
    user_separator = translator.gettext(" and ")

    for group in sorted(grouped_data, key=lambda g: g.channel_name):
        sorted_nicks = sorted(user.nickname for user in group.users)
        if not sorted_nicks:
            continue

        if len(sorted_nicks) == 1:
            user_list = Bold(sorted_nicks[0])
        else:
            # Format as: User1, User2 and User3
            user_list = Bold(
                f"{', '.join(sorted_nicks[:-1])}",
                user_separator,
                sorted_nicks[-1],
            )
        channel_parts.append(Text(user_list, " ", group.channel_name))

    # Combine header and the list of channel parts
    content = as_list(header, as_list(*channel_parts, sep="\n"), sep="\n\n")

    return content.as_html()


class ReportService:
    """Service for generating reports."""

    def __init__(
        self,
        settings: Settings,
        user_repo: UserRepository,
        subscriber_repo: SubscriberRepository,
        ban_repo: BanRepository,
        bot: EventBot,
    ) -> None:
        """Initializes the report service."""
        self._settings = settings
        self._user_repo = user_repo
        self._subscriber_repo = subscriber_repo
        self._ban_repo = ban_repo
        self._bot = bot

    def get_online_users_report(
        self,
        tt_connection: "TeamTalkConnection",
        *,
        is_caller_admin: bool,
        translator: NullTranslations,
    ) -> str:
        """Generates a formatted report of online users."""
        if not tt_connection.instance:
            return translator.gettext("Error: No active TeamTalk connection.")

        all_users = list(tt_connection.cache_manager.online_users_cache.values())
        bot_user_id = tt_connection.instance.getMyUserID()
        server_name = get_effective_server_name(
            tt_connection.instance, translator, self._settings
        )

        grouped_data, total_users = _group_users_for_who_command(
            all_users,
            bot_user_id,
            is_caller_admin=is_caller_admin,
            translator=translator,
        )

        return _format_who_message(
            grouped_data, total_users, translator=translator, server_host=server_name
        )

    async def get_subscribers_info(self, page: int) -> PaginatedResult[SubscriberInfo]:
        """Fetches and prepares a paginated list of subscribers."""
        offset = page * USERS_PER_PAGE
        total_items = await self._subscriber_repo.count_all()
        subscribers = await self._subscriber_repo.get_paginated(offset, USERS_PER_PAGE)

        subscriber_ids = [sub.telegram_id for sub in subscribers]
        user_settings_list = await self._user_repo.get_by_ids(subscriber_ids)
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
                    teamtalk_username=settings.teamtalk_username if settings else None,
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
        offset = page * USERS_PER_PAGE
        total_items = await self._ban_repo.count_with_telegram_id()
        banned_entries = await self._ban_repo.get_paginated_with_telegram_id(
            offset, USERS_PER_PAGE
        )

        banned_ids = [
            entry.telegram_id for entry in banned_entries if entry.telegram_id
        ]
        user_settings_list = await self._user_repo.get_by_ids(banned_ids)
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
                    teamtalk_username=settings.teamtalk_username if settings else None,
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
