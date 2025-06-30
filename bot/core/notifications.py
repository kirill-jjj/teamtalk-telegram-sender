import logging
from datetime import datetime, timedelta
from aiogram import html

import pytalk
from pytalk.instance import TeamTalkInstance
from pytalk.user import User as TeamTalkUser
from sqlalchemy.orm import selectinload # For eager loading related objects
from sqlmodel import select

from bot.config import app_config
from bot.language import get_translator
from bot.database.engine import SessionFactory
from bot.state import SUBSCRIBED_USERS_CACHE
from bot.models import UserSettings, MutedUser, NotificationSetting # Импортируем UserSettings
from bot.telegram_bot.utils import send_telegram_messages_to_list
from bot.constants import (
    NOTIFICATION_EVENT_JOIN,
    NOTIFICATION_EVENT_LEAVE,
    INITIAL_LOGIN_IGNORE_DELAY_SECONDS
)
from bot.core.utils import get_effective_server_name, get_tt_user_display_name

logger = logging.getLogger(__name__)
ttstr = pytalk.instance.sdk.ttstr


def _should_ignore_initial_event(event_type: str, username: str, user_id: int, login_complete_time: datetime | None) -> bool:
    """Checks if the event should be ignored due to recent bot login."""
    reason_for_ignore = ""

    if login_complete_time is None:
        reason_for_ignore = "bot still initializing/reconnecting"
    elif datetime.utcnow() < login_complete_time + timedelta(seconds=INITIAL_LOGIN_IGNORE_DELAY_SECONDS):
        reason_for_ignore = "bot login too recent"
    else:
        return False

    if event_type == NOTIFICATION_EVENT_JOIN: # Log only for join events to reduce noise for leave events during init
        logger.debug(f"Ignoring potential initial sync {event_type} for {username} ({user_id}). Reason: {reason_for_ignore}.")
    return True


def _is_user_globally_ignored(username: str) -> bool:
    """Checks if the user is in the global ignore list from the config."""
    global_ignore_str = app_config.GLOBAL_IGNORE_USERNAMES or ""
    if not global_ignore_str:
        return False

    ignored_set = {name.strip() for name in global_ignore_str.split(',') if name.strip()}
    return username in ignored_set


async def _get_recipients_for_notification(username_to_check: str, event_type: str) -> list[int]:
    """
    Эффективно получает список ID получателей, выполняя один запрос к БД.
    """
    recipients = []

    # Берем копию ID подписчиков из кэша
    subscriber_ids = list(SUBSCRIBED_USERS_CACHE)
    if not subscriber_ids:
        return []

    async with SessionFactory() as session:
        # 1. Одним запросом получаем все настройки для всех подписчиков
        #    Используем `selectinload` для "жадной" загрузки связанных MutedUser,
        #    чтобы избежать дополнительных запросов в цикле.
        stmt = (
            select(UserSettings)
            .options(selectinload(UserSettings.muted_users_list))
            .where(UserSettings.telegram_id.in_(subscriber_ids))
        )
        result = await session.execute(stmt)
        all_settings = result.scalars().all()

        # 2. Создаем словарь для быстрого доступа к настройкам по ID
        settings_map = {s.telegram_id: s for s in all_settings}

        # 3. Теперь итерируем по подписчикам и проверяем все в памяти
        for chat_id in subscriber_ids:
            user_settings = settings_map.get(chat_id)

            # Если по какой-то причине настроек нет (хотя должны быть), пропускаем
            if not user_settings:
                continue

            # Проверка настроек уведомлений
            notification_pref = user_settings.notification_settings
            if notification_pref == NotificationSetting.NONE:
                continue
            if event_type == NOTIFICATION_EVENT_JOIN and notification_pref == NotificationSetting.JOIN_OFF:
                continue
            if event_type == NOTIFICATION_EVENT_LEAVE and notification_pref == NotificationSetting.LEAVE_OFF:
                continue

            # Проверка на Mute
            mute_all_flag = user_settings.mute_all

            # Используем уже загруженный `muted_users_list`
            muted_usernames_set = {mu.muted_teamtalk_username for mu in user_settings.muted_users_list}
            is_muted_explicitly = username_to_check in muted_usernames_set

            should_receive = False
            if mute_all_flag:
                # Если "Mute All", то уведомления приходят только для тех, кто в списке исключений (allowed)
                if is_muted_explicitly:
                    should_receive = True
            else:
                # Иначе, уведомления приходят для всех, КРОМЕ тех, кто в списке (muted)
                if not is_muted_explicitly:
                    should_receive = True

            if should_receive:
                recipients.append(chat_id)

    return recipients


def _generate_join_leave_notification_text(
    tt_user: TeamTalkUser, server_name: str, event_type: str, lang_code: str
) -> str:
    """
    Generates the localized notification text for a join/leave event.
    """
    _ = recipient_translator_func = get_translator(lang_code).gettext

    localized_user_nickname = get_tt_user_display_name(tt_user, recipient_translator_func)

    if event_type == NOTIFICATION_EVENT_JOIN:
        notification_template = _("User {user_nickname} joined server {server_name}")
    else:  # Assuming only JOIN and LEAVE types
        notification_template = _("User {user_nickname} left server {server_name}")

    return notification_template.format(
        user_nickname=html.quote(localized_user_nickname),
        server_name=html.quote(server_name)
    )


async def send_join_leave_notification_logic(
    event_type: str,
    tt_user: TeamTalkUser,
    tt_instance: TeamTalkInstance,
    login_complete_time: datetime | None
):
    default_lang_for_markup_and_log = app_config.DEFAULT_LANG
    _log_markup_translator = get_translator(default_lang_for_markup_and_log).gettext
    user_nickname = get_tt_user_display_name(tt_user, _log_markup_translator) # For logging and markup

    user_username = ttstr(tt_user.username)
    user_id = tt_user.id

    if not user_username:
        logger.warning(f"User {event_type} with empty username (Nickname: {user_nickname}, ID: {user_id}). Skipping.")
        return

    if _should_ignore_initial_event(event_type, user_username, user_id, login_complete_time):
        return

    if _is_user_globally_ignored(user_username):
        logger.debug(f"User {user_username} is globally ignored. Skipping {event_type} notification.")
        return

    recipients = await _get_recipients_for_notification(user_username, event_type)

    if not recipients:
        logger.debug(f"No recipients found for {event_type} event for user {user_username}.")
        return

    logger.info(f"Notifications for {event_type} of {user_username} will be sent to {len(recipients)} users.")

    server_name = get_effective_server_name(tt_instance, _log_markup_translator)

    await send_telegram_messages_to_list(
        bot_token_to_use=app_config.TG_EVENT_TOKEN,
        chat_ids=recipients,
        text_generator=lambda lang_code: _generate_join_leave_notification_text(
            tt_user, server_name, event_type, lang_code
        ),
        tt_user_username_for_markup=user_username, # For potential markup buttons related to the user
        tt_user_nickname_for_markup=user_nickname  # For potential markup buttons
    )
