"""Service layer for user-related operations, like profile deletion."""

import gettext
from html import escape
import logging
from typing import TYPE_CHECKING

import pytalk
from pytalk.user import User as TeamTalkUser
from sqlmodel.ext.asyncio.session import AsyncSession

from bot.constants import (
    WHO_CHANNEL_ID_ROOT,
    WHO_CHANNEL_ID_SERVER_ROOT_ALT,
    WHO_CHANNEL_ID_SERVER_ROOT_ALT2,
)
from bot.core.enums import Actor
from bot.database import crud
from bot.models import MutedUser, MuteListMode, NotificationSetting, OperationResult, UserSettings
from bot.teamtalk_bot.connection import TeamTalkConnection
from bot.teamtalk_bot.utils import get_tt_user_display_name
from bot.telegram_bot.models import WhoChannelGroup, WhoUser

from . import _utils
from ._utils import managed_db_transaction

if TYPE_CHECKING:
    from bot.services_container import Services

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


def _get_user_display_channel_name(
    user_obj: TeamTalkUser, *, is_caller_admin: bool, translator: "gettext.GNUTranslations"
) -> str:
    channel_obj = user_obj.channel
    user_display_channel_name = ""
    is_channel_hidden = False

    if channel_obj:
        try:
            if (
                hasattr(pytalk.instance.sdk, "ChannelType")
                and hasattr(channel_obj, "channel_type")
                and isinstance(channel_obj.channel_type, int)
                and (channel_obj.channel_type & pytalk.instance.sdk.ChannelType.CHANNEL_HIDDEN) != 0
            ):
                is_channel_hidden = True
        except AttributeError:  # Catches missing ChannelType or channel_obj.channel_type
            log_msg = (
                f"SDK, ChannelType or channel_type attribute missing, "
                f"cannot determine if channel {ttstr(channel_obj.name)} ({channel_obj.id}) is hidden."
            )
            logger.warning(log_msg)
        except TypeError as e_chan_type:
            log_msg = f"TypeError checking channel type for {ttstr(channel_obj.name)} ({channel_obj.id}): {e_chan_type}"
            logger.exception(log_msg)
        except Exception as e_chan:
            log_msg = (
                f"Unexpected error checking channel type for {ttstr(channel_obj.name)} ({channel_obj.id}): {e_chan}"
            )
            logger.exception(log_msg)

    server_root_ids = [WHO_CHANNEL_ID_ROOT, WHO_CHANNEL_ID_SERVER_ROOT_ALT, WHO_CHANNEL_ID_SERVER_ROOT_ALT2]
    if channel_obj and channel_obj.id not in server_root_ids:
        if is_caller_admin or not is_channel_hidden:
            channel_name_str = ttstr(channel_obj.name)
            user_display_channel_name = translator.gettext("in {channel_name}").format(channel_name=channel_name_str)
        else:
            user_display_channel_name = translator.gettext("under server")
    elif channel_obj and channel_obj.id == WHO_CHANNEL_ID_ROOT:
        user_display_channel_name = translator.gettext("in root channel")
    elif not channel_obj or (
        hasattr(channel_obj, "id")
        and channel_obj.id in [WHO_CHANNEL_ID_SERVER_ROOT_ALT, WHO_CHANNEL_ID_SERVER_ROOT_ALT2]
    ):
        user_display_channel_name = translator.gettext("under server")
    else:  # Should ideally not be reached if channel_obj exists and ID is checked
        user_display_channel_name = translator.gettext("in unknown location")

    return user_display_channel_name


def _group_users_for_who_command(
    users: list[TeamTalkUser], bot_user_id: int | None, *, is_caller_admin: bool, translator: "gettext.GNUTranslations"
) -> tuple[list[WhoChannelGroup], int]:
    channels_display_data: dict[str, list[str]] = {}
    users_added_to_groups_count = 0

    for user_obj in users:
        if bot_user_id is not None and user_obj.id == bot_user_id and not is_caller_admin:
            continue

        user_display_channel_name = _get_user_display_channel_name(
            user_obj, is_caller_admin=is_caller_admin, translator=translator
        )

        if user_display_channel_name not in channels_display_data:
            channels_display_data[user_display_channel_name] = []

        user_nickname = get_tt_user_display_name(user_obj, translator)
        channels_display_data[user_display_channel_name].append(escape(user_nickname))
        users_added_to_groups_count += 1

    result_groups = [
        WhoChannelGroup(channel_name=name, users=[WhoUser(nickname=nick) for nick in nicks])
        for name, nicks in channels_display_data.items()
    ]
    return result_groups, users_added_to_groups_count


def _format_who_message(
    grouped_data: list[WhoChannelGroup],
    total_users: int,
    translator: "gettext.GNUTranslations",
    server_host: str | None,
) -> str:
    _ = translator.gettext
    ngettext = translator.ngettext

    if total_users == 0:
        no_users_text = _("No users found online")
        if server_host:
            no_users_text = _("No users found online on server {server_host}.").format(server_host=server_host)
        else:
            no_users_text = _("No users found online.")
        return no_users_text

    sorted_groups = sorted(grouped_data, key=lambda group: group.channel_name)

    if server_host:
        header_template = ngettext(
            "There is {user_count} user on the server {server_host}:\n",
            "There are {user_count} users on the server {server_host}:\n",
            total_users,
        )
        text_reply = header_template.format(user_count=total_users, server_host=server_host)
    else:
        header_template = ngettext(
            "There is {user_count} user on the server:\n", "There are {user_count} users on the server:\n", total_users
        )
        text_reply = header_template.format(user_count=total_users)

    channel_info_parts: list[str] = []
    for group in sorted_groups:
        sorted_nicknames = sorted([user.nickname for user in group.users])
        user_text_segment = ""
        if sorted_nicknames:
            if len(sorted_nicknames) > 1:
                user_separator = translator.gettext(" and ")
                user_list_except_last_segment = ", ".join(sorted_nicknames[:-1])
                user_text_segment = f"<b>{user_list_except_last_segment}{user_separator}{sorted_nicknames[-1]}</b>"
            else:
                user_text_segment = f"<b>{sorted_nicknames[0]}</b>"
            channel_info_parts.append(f"{user_text_segment} {group.channel_name}")

    if channel_info_parts:
        text_reply += "\n" + "\n".join(channel_info_parts)
    return text_reply


async def get_online_users_report(
    tt_connection: TeamTalkConnection, *, is_caller_admin: bool, translator: gettext.GNUTranslations
) -> str:
    """Generates a formatted report of online users."""
    if not tt_connection.instance:
        return translator.gettext("Error: No active TeamTalk connection.")

    all_users_list = list(tt_connection.online_users_cache.values())
    bot_user_id = tt_connection.instance.getMyUserID()
    server_host = tt_connection.server_info.host

    grouped_data, total_users = _group_users_for_who_command(
        all_users_list, bot_user_id, is_caller_admin=is_caller_admin, translator=translator
    )

    return _format_who_message(grouped_data, total_users, translator=translator, server_host=server_host)


async def delete_full_user_profile(
    session: AsyncSession,
    telegram_id: int,
    services: "Services",
) -> bool:
    """Orchestrates the full deletion of a user's profile.

    This includes database records and cache entries via the services container.
    """
    logger.info("Attempting to delete full user profile for Telegram ID: %s", telegram_id)
    async with managed_db_transaction(session, logger) as transaction_success:
        if not transaction_success:
            return False

        user_settings_deleted, subscribed_user_deleted = await crud._delete_user_data_from_db(session, telegram_id)

        if not user_settings_deleted and not subscribed_user_deleted:
            logger.info("No DB data found for Telegram ID %s to delete.", telegram_id)

        services.cache.remove_full_user_profile(telegram_id)
        logger.info(
            "Full user profile deletion process completed for Telegram ID: %s. "
            "DB changes (if any) committed. Caches cleared via CacheService.",
            telegram_id,
        )
        return True


async def update_mute_mode(
    session: AsyncSession,
    services: "Services",
    user_settings: UserSettings,
    new_mode: MuteListMode,
    actor: Actor = Actor.USER,
) -> UserSettings | None:
    """Sets the mute list mode for a user."""
    log_context = f" by {actor.value}"
    return await _utils._update_user_setting_field(
        session=session,
        services=services,
        settings_to_update=user_settings,
        field_name="mute_list_mode",
        new_value=new_mode,
        log_context=log_context,
    )


async def update_language(
    session: AsyncSession,
    services: "Services",
    user_settings: UserSettings,
    new_lang_code: str,
    actor: Actor = Actor.USER,
) -> UserSettings | None:
    """Updates the language for a user."""
    log_context = f" by {actor.value}"
    updated_settings = await _utils._update_user_setting_field(
        session=session,
        services=services,
        settings_to_update=user_settings,
        field_name="language_code",
        new_value=new_lang_code,
        log_context=log_context,
    )
    if updated_settings:
        await _utils.update_user_bot_commands(
            telegram_id=user_settings.telegram_id, new_lang_code=new_lang_code, services=services
        )
    return updated_settings


async def update_noon_setting(
    session: AsyncSession,
    services: "Services",
    user_settings: UserSettings,
    actor: Actor = Actor.USER,
) -> UserSettings | None:
    """Toggles the NOON (Not On Online Notifications) setting for a user.

    If NOON is enabled, it also ensures that 'not_on_online_confirmed' is set to True.
    Handles DB session, commit, rollback, and cache update via _update_user_setting_field.
    Returns the updated UserSettings object or None on failure.
    """
    # The session merge is now handled by _update_user_setting_field.
    # We need to get the current value from the passed `user_settings` object before updating.
    new_noon_enabled_value = not user_settings.not_on_online_enabled

    # Update the 'not_on_online_enabled' field
    updated_settings_noon_toggle = await _utils._update_user_setting_field(
        session=session,
        services=services,
        settings_to_update=user_settings,
        field_name="not_on_online_enabled",
        new_value=new_noon_enabled_value,
        log_context=f" by {actor.value} (toggle NOON)",
    )

    if not updated_settings_noon_toggle:
        # Error occurred and was logged by _update_user_setting_field
        return None

    # If NOON was enabled and not yet confirmed, attempt to set not_on_online_confirmed to True
    # Use the settings object returned by the first update call
    if updated_settings_noon_toggle.not_on_online_enabled and not updated_settings_noon_toggle.not_on_online_confirmed:
        confirmed_settings = await _utils._update_user_setting_field(
            session=session,
            services=services,
            settings_to_update=updated_settings_noon_toggle,  # Use the already updated object
            field_name="not_on_online_confirmed",
            new_value=True,
            log_context=f" by {actor.value} (confirm NOON after toggle)",
        )
        if not confirmed_settings:
            # Log a warning if the confirmation step failed
            logger.warning(
                "NOON setting was toggled to enabled for user %s, "
                "but the subsequent confirmation of 'not_on_online_confirmed' failed. "
                "The 'not_on_online_enabled' field remains updated.",
                updated_settings_noon_toggle.telegram_id,
            )
            # Return the settings from the first successful update, as the primary action succeeded.
            return updated_settings_noon_toggle

        return confirmed_settings  # Both updates succeeded

    # This path is reached if:
    # 1. NOON was toggled to False.
    # 2. NOON was toggled to True, but 'not_on_online_confirmed' was already True.
    # In these cases, the 'updated_settings_noon_toggle' from the first call is the final state.
    return updated_settings_noon_toggle


async def update_notification_preference(
    session: AsyncSession,
    services: "Services",
    user_settings: UserSettings,
    new_pref: "NotificationSetting",
    actor: Actor = Actor.USER,
) -> UserSettings | None:
    """Sets the notification preference for a user."""
    log_context = f" by {actor.value}"
    return await _utils._update_user_setting_field(
        session=session,
        services=services,
        settings_to_update=user_settings,
        field_name="notification_settings",
        new_value=new_pref,
        log_context=log_context,
    )


async def process_new_subscription(
    session: AsyncSession,
    user_settings: UserSettings,
    tt_username: str,
    services: "Services",
) -> bool:
    """Handles all DB and cache operations for a new subscription via deeplink."""
    async with managed_db_transaction(session, logger) as transaction_success:
        if not transaction_success:
            return False

        was_newly_added = await crud.add_subscriber(session, user_settings.telegram_id)
        if was_newly_added:
            logger.info("User %s newly subscribed via deeplink.", user_settings.telegram_id)
        else:
            logger.info("User %s re-confirmed subscription via deeplink.", user_settings.telegram_id)
        if not services.cache.is_subscribed(user_settings.telegram_id):
            services.cache.add_subscriber(user_settings.telegram_id)

        settings_after_tt_update = await _utils._update_user_setting_field(
            session=session,
            services=services,
            settings_to_update=user_settings,
            field_name="teamtalk_username",
            new_value=tt_username,
            log_context=" (new subscription)",
        )
        if not settings_after_tt_update:
            return False

        settings_after_noon_confirm = await _utils._update_user_setting_field(
            session=session,
            services=services,
            settings_to_update=settings_after_tt_update,
            field_name="not_on_online_confirmed",
            new_value=True,
            log_context=" (new subscription)",
        )
        return bool(settings_after_noon_confirm)


async def toggle_mute_status_for_tt_user(
    session: AsyncSession,
    user_settings: UserSettings,
    tt_username_to_toggle: str,
    services: "Services",
    translator: "gettext.GNUTranslations",
) -> OperationResult:
    """Toggles the mute status of a TeamTalk user using a managed transaction."""
    _ = translator.gettext
    if user_settings.muted_users_list is None:
        user_settings.muted_users_list = []

    existing_entry = next(
        (entry for entry in user_settings.muted_users_list if entry.muted_teamtalk_username == tt_username_to_toggle),
        None,
    )

    log_context = f" while toggling mute for '{tt_username_to_toggle}' for user {user_settings.telegram_id}"
    resulting_action = "unmuted" if existing_entry else "muted"

    try:
        async with managed_db_transaction(session, logger, log_context):
            if existing_entry:
                user_settings.muted_users_list.remove(existing_entry)
                await session.delete(existing_entry)
                logger.info("Unmuting TT user '%s' for TG user %s.", tt_username_to_toggle, user_settings.telegram_id)
            else:
                new_entry = MutedUser(
                    user_settings_telegram_id=user_settings.telegram_id,
                    muted_teamtalk_username=tt_username_to_toggle,
                )
                user_settings.muted_users_list.append(new_entry)
                session.add(new_entry)
                logger.info("Muting TT user '%s' for TG user %s.", tt_username_to_toggle, user_settings.telegram_id)
    except Exception:
        return OperationResult(
            success=False, message_key=_("An error occurred while changing the mute status. Please try again.")
        )

    # This block executes only if the transaction was successful
    await session.refresh(user_settings, attribute_names=["muted_users_list"])
    services.cache.update_user_settings(user_settings)
    logger.info(
        "Successfully toggled mute for '%s' for user %s to '%s'. Cache updated.",
        tt_username_to_toggle,
        user_settings.telegram_id,
        resulting_action,
    )
    message_key = _("mute_toggle_success_muted") if resulting_action == "muted" else _("mute_toggle_success_unmuted")
    return OperationResult(
        success=True,
        message_key=message_key,
        message_args={"username": tt_username_to_toggle},
        user_settings=user_settings,
    )
