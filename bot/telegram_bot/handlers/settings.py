import logging
from aiogram import Router, html, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.localization import get_text
from bot.database.models import NotificationSetting, UserSettings as UserSettingsDbModel
from bot.core.user_settings import (
    UserSpecificSettings,
    update_user_settings_in_db,
    USER_SETTINGS_CACHE # For direct update after DB
)
from bot.constants import (
    DEFAULT_LANGUAGE,
    MUTE_ACTION_MUTE, MUTE_ACTION_UNMUTE
)

logger = logging.getLogger(__name__)
settings_router = Router(name="settings_router")

@settings_router.message(Command("cl"))
async def cl_command_handler(
    message: Message,
    command: CommandObject,
    session: AsyncSession, # From DbSessionMiddleware
    language: str, # Current language from UserSettingsMiddleware
    user_specific_settings: UserSpecificSettings # From UserSettingsMiddleware
):
    if not message.from_user: return

    new_lang_candidate = command.args
    if not new_lang_candidate or new_lang_candidate.lower() not in [DEFAULT_LANGUAGE, "ru"]: # Assuming 'en' and 'ru'
        await message.reply(get_text(CL_PROMPT, language)) # Reply in current language
        return

    new_lang_val = new_lang_candidate.lower()
    telegram_id_val = message.from_user.id

    if user_specific_settings.language == new_lang_val:
        await message.reply(get_text(CL_CHANGED, new_lang_val, new_lang=new_lang_val)) # Already set
        return

    user_specific_settings.language = new_lang_val
    await update_user_settings_in_db(session, telegram_id_val, user_specific_settings)
    # Cache is updated within update_user_settings_in_db

    await message.reply(get_text(CL_CHANGED, new_lang_val, new_lang=new_lang_val)) # Reply in new language


async def _set_notification_preference(
    message: Message,
    new_setting: NotificationSetting, # The enum member
    session: AsyncSession,
    user_specific_settings: UserSpecificSettings
):
    if not message.from_user: return
    telegram_id = message.from_user.id
    current_language = user_specific_settings.language # Get current lang for reply

    if user_specific_settings.notification_settings == new_setting:
        # Optionally inform user it's already set, or just do nothing
        pass # For now, just update if different

    user_specific_settings.notification_settings = new_setting
    await update_user_settings_in_db(session, telegram_id, user_specific_settings)

    settings_messages_map = {
        NotificationSetting.ALL: NOTIFY_ALL_SET,
        NotificationSetting.JOIN_OFF: NOTIFY_JOIN_OFF_SET,
        NotificationSetting.LEAVE_OFF: NOTIFY_LEAVE_OFF_SET,
        NotificationSetting.NONE: NOTIFY_NONE_SET,
    }
    reply_text_key = settings_messages_map.get(new_setting, "error_occurred") # Fallback
    await message.reply(get_text(reply_text_key, current_language))


@settings_router.message(Command("notify_all"))
async def notify_all_cmd(message: Message, session: AsyncSession, user_specific_settings: UserSpecificSettings):
    await _set_notification_preference(message, NotificationSetting.ALL, session, user_specific_settings)

@settings_router.message(Command("notify_join_off"))
async def notify_join_off_cmd(message: Message, session: AsyncSession, user_specific_settings: UserSpecificSettings):
    await _set_notification_preference(message, NotificationSetting.JOIN_OFF, session, user_specific_settings)

@settings_router.message(Command("notify_leave_off"))
async def notify_leave_off_cmd(message: Message, session: AsyncSession, user_specific_settings: UserSpecificSettings):
    await _set_notification_preference(message, NotificationSetting.LEAVE_OFF, session, user_specific_settings)

@settings_router.message(Command("notify_none"))
async def notify_none_cmd(message: Message, session: AsyncSession, user_specific_settings: UserSpecificSettings):
    await _set_notification_preference(message, NotificationSetting.NONE, session, user_specific_settings)


async def _update_mute_user_in_settings(
    session: AsyncSession,
    telegram_id: int,
    username_to_process: str,
    action: str, # "mute" or "unmute"
    user_specific_settings: UserSpecificSettings
):
    if action == MUTE_ACTION_MUTE:
        user_specific_settings.muted_users_set.add(username_to_process)
    elif action == MUTE_ACTION_UNMUTE:
        user_specific_settings.muted_users_set.discard(username_to_process)
    else:
        logger.warning(f"Unknown mute action: {action}")
        return

    await update_user_settings_in_db(session, telegram_id, user_specific_settings)


async def _set_mute_all_in_settings(
    session: AsyncSession,
    telegram_id: int,
    mute_all_status: bool,
    user_specific_settings: UserSpecificSettings
):
    user_specific_settings.mute_all_flag = mute_all_status
    if not mute_all_status: # When disabling mute_all, clear the exception list
        user_specific_settings.muted_users_set.clear()
    # If enabling mute_all, the existing muted_users_set becomes the exception list.
    await update_user_settings_in_db(session, telegram_id, user_specific_settings)


@settings_router.message(Command("mute"))
async def mute_command_handler(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    language: str,
    user_specific_settings: UserSpecificSettings
):
    if not message.from_user: return

    args_val = command.args
    if not args_val or not args_val.lower().startswith("user "):
        await message.reply(get_text(MUTE_PROMPT_USER, language))
        return

    username_to_mute_val = args_val[len("user "):].strip()
    if not username_to_mute_val:
         await message.reply(get_text(MUTE_USERNAME_EMPTY, language))
         return

    telegram_id_val = message.from_user.id

    # Behavior depends on mute_all_flag
    # If mute_all is OFF: muted_users_set is a block list. Adding to it mutes.
    # If mute_all is ON: muted_users_set is an allow list (exceptions). Adding to it UNMUTES (allows notifications).
    # The command "/mute" should consistently mean "I don't want notifications from this user".
    # So, if mute_all is ON, "/mute foo" means "remove foo from exceptions".
    # If mute_all is OFF, "/mute foo" means "add foo to block list".

    if user_specific_settings.mute_all_flag: # Mute all is ON (list is exceptions)
        if username_to_mute_val in user_specific_settings.muted_users_set: # Was an exception, now remove
            await _update_mute_user_in_settings(session, telegram_id_val, username_to_mute_val, MUTE_ACTION_UNMUTE, user_specific_settings)
            await message.reply(get_text(MUTE_NOW_MUTED, language, username=html.quote(username_to_mute_val)))
        else: # Was not an exception, already effectively muted
            await message.reply(get_text(MUTE_ALREADY_MUTED, language, username=html.quote(username_to_mute_val)))
    else: # Mute all is OFF (list is block list)
        if username_to_mute_val in user_specific_settings.muted_users_set: # Already in block list
            await message.reply(get_text(MUTE_ALREADY_MUTED, language, username=html.quote(username_to_mute_val)))
        else: # Not in block list, add to mute
            await _update_mute_user_in_settings(session, telegram_id_val, username_to_mute_val, MUTE_ACTION_MUTE, user_specific_settings)
            await message.reply(get_text(MUTE_NOW_MUTED, language, username=html.quote(username_to_mute_val)))


@settings_router.message(Command("unmute"))
async def unmute_command_handler(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    language: str,
    user_specific_settings: UserSpecificSettings
):
    if not message.from_user: return

    args_val = command.args
    if not args_val or not args_val.lower().startswith("user "):
        await message.reply(get_text(UNMUTE_PROMPT_USER, language))
        return

    username_to_unmute_val = args_val[len("user "):].strip()
    if not username_to_unmute_val:
         await message.reply(get_text(MUTE_USERNAME_EMPTY, language)) # Re-use username empty message
         return

    telegram_id_val = message.from_user.id

    # Command "/unmute" should consistently mean "I DO want notifications from this user".
    # If mute_all is ON: "/unmute foo" means "add foo to exceptions".
    # If mute_all is OFF: "/unmute foo" means "remove foo from block list".

    if user_specific_settings.mute_all_flag: # Mute all is ON (list is exceptions)
        if username_to_unmute_val not in user_specific_settings.muted_users_set: # Not an exception, add it
            await _update_mute_user_in_settings(session, telegram_id_val, username_to_unmute_val, MUTE_ACTION_MUTE, user_specific_settings) # MUTE action adds to set
            await message.reply(get_text(UNMUTE_NOW_UNMUTED, language, username=html.quote(username_to_unmute_val)))
        else: # Already an exception, effectively unmuted
            # To avoid confusion, we can just confirm it's unmuted.
            await message.reply(get_text(UNMUTE_NOW_UNMUTED, language, username=html.quote(username_to_unmute_val))) # Or a specific "already unmuted"
    else: # Mute all is OFF (list is block list)
        if username_to_unmute_val in user_specific_settings.muted_users_set: # In block list, remove
            await _update_mute_user_in_settings(session, telegram_id_val, username_to_unmute_val, MUTE_ACTION_UNMUTE, user_specific_settings) # UNMUTE action removes from set
            await message.reply(get_text(UNMUTE_NOW_UNMUTED, language, username=html.quote(username_to_unmute_val)))
        else: # Not in block list, already effectively unmuted
            await message.reply(get_text(UNMUTE_NOT_IN_LIST, language, username=html.quote(username_to_unmute_val)))


@settings_router.message(Command("mute_all"))
async def mute_all_command_handler(
    message: Message,
    session: AsyncSession,
    language: str,
    user_specific_settings: UserSpecificSettings
):
    if not message.from_user: return
    await _set_mute_all_in_settings(session, message.from_user.id, True, user_specific_settings)
    await message.reply(get_text(MUTE_ALL_ENABLED, language))


@settings_router.message(Command("unmute_all"))
async def unmute_all_command_handler(
    message: Message,
    session: AsyncSession,
    language: str,
    user_specific_settings: UserSpecificSettings
):
    if not message.from_user: return
    await _set_mute_all_in_settings(session, message.from_user.id, False, user_specific_settings)
    await message.reply(get_text(UNMUTE_ALL_DISABLED, language))


@settings_router.message(Command("toggle_noon"))
async def toggle_noon_command_handler(
    message: Message,
    session: AsyncSession,
    language: str,
    user_specific_settings: UserSpecificSettings
):
    if not message.from_user: return
    telegram_id = message.from_user.id

    if not user_specific_settings.teamtalk_username or not user_specific_settings.not_on_online_confirmed:
        await message.reply(get_text(NOON_NOT_CONFIGURED, language))
        return

    new_enabled_status = not user_specific_settings.not_on_online_enabled
    user_specific_settings.not_on_online_enabled = new_enabled_status
    await update_user_settings_in_db(session, telegram_id, user_specific_settings)

    reply_key = NOON_TOGGLED_ENABLED if new_enabled_status else NOON_TOGGLED_DISABLED
    # Ensure teamtalk_username is not None before quoting, though check above should cover it
    tt_username_for_reply = user_specific_settings.teamtalk_username or "your TeamTalk user"
    reply_text = get_text(reply_key, language, tt_username=html.quote(tt_username_for_reply))
    logger.info(f"User {telegram_id} toggled 'not on online' to {new_enabled_status} for TT user {user_specific_settings.teamtalk_username}")
    await message.reply(reply_text)


@settings_router.message(Command("my_noon_status"))
async def my_noon_status_command_handler(
    message: Message,
    language: str,
    user_specific_settings: UserSpecificSettings
):
    if not user_specific_settings.teamtalk_username or not user_specific_settings.not_on_online_confirmed:
        reply_text = get_text(NOON_STATUS_NOT_CONFIGURED, language)
    else:
        status_key_en = NOON_STATUS_ENABLED_EN if user_specific_settings.not_on_online_enabled else NOON_STATUS_DISABLED_EN
        status_key_ru = NOON_STATUS_ENABLED_RU if user_specific_settings.not_on_online_enabled else NOON_STATUS_DISABLED_RU

        # Get the status text in the user's selected language for the main message
        # The placeholders {status} and {status_ru} are a bit confusing if the main text is already localized.
        # Let's simplify: the main message will use the localized status.
        current_lang_status_text = ""
        if language == "ru":
            current_lang_status_text = get_text(status_key_ru, "ru")
        else: # en or default
            current_lang_status_text = get_text(status_key_en, "en")


        reply_text = get_text(
            NOON_STATUS_REPORT,
            language, # User's current language for the main template
            status=current_lang_status_text, # This will be used if {status} is in the NOON_STATUS_REPORT for the current language
            status_ru=get_text(status_key_ru, "ru"), # Provide RU version for {status_ru} if template uses it
            status_en=get_text(status_key_en, "en"), # Provide EN version for {status_en} if template uses it
            tt_username=html.quote(user_specific_settings.teamtalk_username or "N/A")
        )
        # A better approach for NOON_STATUS_REPORT would be:
        # "noon_status_report_enabled": {"en": "'Not on online' notifications are ENABLED for TT user '{tt_username}'.", "ru": "Уведомления 'не в сети' ВКЛЮЧЕНЫ для пользователя TT '{tt_username}'."}
        # "noon_status_report_disabled": {"en": "'Not on online' notifications are DISABLED for TT user '{tt_username}'.", "ru": "Уведомления 'не в сети' ВЫКЛЮЧЕНЫ для пользователя TT '{tt_username}'."}
        # Then select the key based on enabled status.
        # For now, sticking to the original structure:
        effective_status_text = get_text(status_key_en, "en") if language == "en" else get_text(status_key_ru, "ru")
        reply_text = get_text(
            NOON_STATUS_REPORT, language,
            status=effective_status_text, # This is if the template uses {status}
            status_ru=get_text(status_key_ru, "ru"), # This is if the template uses {status_ru}
            tt_username=html.quote(user_specific_settings.teamtalk_username or "N/A")
        )


    await message.reply(reply_text)
