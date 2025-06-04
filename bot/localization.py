import logging
# DEFAULT_LANGUAGE import removed
from bot.config import app_config

logger = logging.getLogger(__name__)

LOCALIZED_STRINGS = {
    "start_hello": {"en": "Hello! Use /help to see available commands.", "ru": "Привет! Используйте /help для просмотра доступных команд."},
    "deeplink_invalid_or_expired": {"en": "Invalid or expired deeplink.", "ru": "Недействительная или истекшая ссылка."},
    "deeplink_wrong_account": {"en": "This confirmation link was intended for a different Telegram account.", "ru": "Эта ссылка для подтверждения предназначена для другого Telegram аккаунта."},
    "deeplink_subscribed": {"en": "You have successfully subscribed to notifications.", "ru": "Вы успешно подписались на уведомления."},
    "deeplink_already_subscribed": {"en": "You are already subscribed to notifications.", "ru": "Вы уже подписаны на уведомления."},
    "deeplink_unsubscribed": {"en": "You have successfully unsubscribed from notifications.", "ru": "Вы успешно отписались от уведомления."},
    "deeplink_not_subscribed": {"en": "You were not subscribed to notifications.", "ru": "Вы не были подписаны на уведомления."},
    "deeplink_noon_confirm_missing_payload": {"en": "Error: Missing TeamTalk username in confirmation link.", "ru": "Ошибка: В ссылке подтверждения отсутствует имя пользователя TeamTalk."},
    "deeplink_noon_confirmed": {"en": "'Not on online' notifications enabled for TeamTalk user '{tt_username}'. You will receive silent notifications when this user is online on TeamTalk.", "ru": "Уведомления 'не в сети' включены для пользователя TeamTalk '{tt_username}'. Вы будете получать тихие уведомления, когда этот пользователь в сети TeamTalk."},
    "deeplink_subscribed_noon_linked_now_enabled": {
        "en": "You are subscribed. 'Not on Online' feature is linked for TeamTalk user '{tt_username}' and is currently ENABLED.",
        "ru": "Вы подписаны. Функция 'не в сети' связана с пользователем TeamTalk '{tt_username}' и сейчас ВКЛЮЧЕНА."
    },
    "deeplink_subscribed_noon_linked_now_disabled": {
        "en": "You are subscribed. 'Not on Online' feature is linked for TeamTalk user '{tt_username}' and is currently DISABLED.",
        "ru": "Вы подписаны. Функция 'не в сети' связана с пользователем TeamTalk '{tt_username}' и сейчас ВЫКЛЮЧЕНА."
    },
    "deeplink_invalid_action": {"en": "Invalid deeplink action.", "ru": "Неверное действие deeplink."},
    "error_occurred": {"en": "An error occurred.", "ru": "Произошла ошибка."},
    "tt_bot_not_connected": {"en": "TeamTalk bot is not connected.", "ru": "Бот TeamTalk не подключен."},
    "tt_error_getting_users": {"en": "Error getting users from TeamTalk.", "ru": "Ошибка получения пользователей из TeamTalk."},
    "who_channel_in": {"en": "in {channel_name}", "ru": "в {channel_name}"},
    "who_channel_under_server": {"en": "under server", "ru": "под сервером"},
    "who_channel_root": {"en": "in root channel", "ru": "в корневом канале"},
    "who_channel_unknown_location": {"en": "in unknown location", "ru": "в неизвестном месте"},
    "who_user_unknown": {"en": "unknown user", "ru": "неизвестный пользователь"},
    "who_and_separator": {"en": " and ", "ru": " и "},
    "who_users_count_singular": {"en": "user", "ru": "пользователь"},
    "who_users_count_plural_2_4": {"en": "users", "ru": "пользователя"},
    "who_users_count_plural_5_more": {"en": "users", "ru": "пользователей"},
    "who_header": {"en": "There are {user_count} {users_word} on the server:\n", "ru": "На сервере сейчас {user_count} {users_word}:\n"},
    "who_no_users_online": {"en": "No users found online.", "ru": "Пользователей онлайн не найдено."},
    "cl_prompt": {"en": "Please specify the language. Example: /cl en or /cl ru.", "ru": "Укажите язык. Пример: /cl en или /cl ru."},
    "cl_changed": {"en": "Language changed to {new_lang}.", "ru": "Язык изменен на {new_lang}."},
    "notify_all_set": {"en": "Join and leave notifications are enabled.", "ru": "Уведомления о входах и выходах включены."},
    "notify_join_off_set": {"en": "Only leave notifications are enabled.", "ru": "Включены только уведомления о выходах."},
    "notify_leave_off_set": {"en": "Only join notifications are enabled.", "ru": "Включены только уведомления о входах."},
    "notify_none_set": {"en": "Join and leave notifications are disabled.", "ru": "Уведомления о входах и выходах отключены."},
    "mute_prompt_user": {"en": "Please specify username to mute in format: /mute user <username>.", "ru": "Пожалуйста, укажите имя пользователя для мьюта в формате: /mute user <username>."},
    "mute_username_empty": {"en": "Username cannot be empty.", "ru": "Имя пользователя не может быть пустым."},
    "mute_already_muted": {"en": "User {username} was already muted.", "ru": "Пользователь {username} уже был замьючен."},
    "mute_now_muted": {"en": "User {username} is now muted.", "ru": "Пользователь {username} теперь замьючен."},
    "unmute_prompt_user": {"en": "Please specify username to unmute in format: /unmute user <username>.", "ru": "Пожалуйста, укажите имя пользователя для размьюта в формате: /unmute user <username>."},
    "unmute_now_unmuted": {"en": "User {username} is now unmuted.", "ru": "Пользователь {username} теперь размьючен."},
    "unmute_not_in_list": {"en": "User {username} was not in the mute list.", "ru": "Пользователь {username} не был в списке мьюта."},
    "mute_all_enabled": {"en": "Mute all for join/leave notifications enabled (only exceptions will be notified).", "ru": "Мьют всех для уведомлений о входе/выходе включен (уведомления будут приходить только для исключений)."},
    "unmute_all_disabled": {"en": "Mute all for join/leave notifications disabled (muted users won't be notified).", "ru": "Мьют всех для уведомлений о входе/выходе выключен (замьюченные пользователи не будут получать уведомления)."},
    "noon_not_configured": {"en": "The 'not on online' feature is not configured for your account. Please set it up via TeamTalk using `/not on online`.", "ru": "Функция 'не в сети' не настроена для вашего аккаунта. Пожалуйста, настройте ее через TeamTalk командой `/not on online`."},
    "noon_toggled_enabled": {"en": "'Not on online' notifications are now ENABLED for TeamTalk user '{tt_username}'. You will receive silent notifications when this user is online.", "ru": "Уведомления 'не в сети' теперь ВКЛЮЧЕНЫ для пользователя TeamTalk '{tt_username}'. Вы будете получать тихие уведомления, когда этот пользователь в сети."},
    "noon_toggled_disabled": {"en": "'Not on online' notifications are now DISABLED for TeamTalk user '{tt_username}'. Notifications will be sent normally.", "ru": "Уведомления 'не в сети' теперь ВЫКЛЮЧЕНЫ для пользователя TeamTalk '{tt_username}'. Уведомления будут приходить как обычно."},
    "noon_error_updating": {"en": "Error updating settings. Please try again.", "ru": "Ошибка обновления настроек. Пожалуйста, попробуйте снова."},
    "noon_status_not_configured": {"en": "'Not on online' feature is not configured for your account. Use `/not on online` in TeamTalk to set it up.", "ru": "Функция 'не в сети' не настроена для вашего аккаунта. Используйте `/not on online` в TeamTalk для настройки."},
    "noon_status_report": {"en": "'Not on online' notifications are {status} for TeamTalk user '{tt_username}'.", "ru": "Уведомления 'не в сети' {status} для пользователя TeamTalk '{tt_username}'."},
    "noon_status_enabled": {"en": "ENABLED", "ru": "ВКЛЮЧЕНА"},
    "noon_status_disabled": {"en": "DISABLED", "ru": "ВЫКЛЮЧЕНА"},
    "callback_invalid_data": {"en": "Invalid data received.", "ru": "Получены неверные данные."},
    "callback_no_permission": {"en": "You do not have permission to execute this action.", "ru": "У вас нет прав на выполнение этого действия."},
    "callback_error_find_user_tt": {"en": "Error finding user on TeamTalk.", "ru": "Ошибка поиска пользователя в TeamTalk."},
    "callback_user_id_info": {"en": "User {user_nickname} has ID: {user_id}", "ru": "Пользователь {user_nickname} имеет ID: {user_id}"},
    "callback_user_kicked": {"en": "User {user_nickname} kicked from server.", "ru": "Пользователь {user_nickname} был исключен с сервера."},
    "callback_user_banned_kicked": {"en": "User {user_nickname} banned and kicked from server.", "ru": "Пользователь {user_nickname} был забанен и выкинут с сервера."},
    "callback_error_action_user": {"en": "Error {action}ing user {user_nickname}: {error}", "ru": "Ошибка {action_ru} пользователя {user_nickname}: {error}"},
    "callback_action_kick_gerund_ru": "исключения", "callback_action_ban_gerund_ru": "бана",
    "callback_user_not_found_anymore": {"en": "User not found on server anymore.", "ru": "Пользователь больше не найден на сервере."},
    "callback_unknown_action": {"en": "Unknown action.", "ru": "Неизвестное действие."},
    "toggle_ignore_error_processing": {"en": "Error processing request.", "ru": "Ошибка обработки запроса."},
    "toggle_ignore_error_empty_username": {"en": "Error: Empty username.", "ru": "Ошибка: Пустое имя пользователя."},
    "toggle_ignore_now_ignored": {"en": "User {nickname} is now ignored.", "ru": "Пользователь {nickname} теперь игнорируется."},
    "toggle_ignore_no_longer_ignored": {"en": "User {nickname} is no longer ignored.", "ru": "Пользователь {nickname} больше не игнорируется."},
    "toggle_ignore_button_text": {"en": "Toggle ignore status: {nickname}", "ru": "Переключить статус игнорирования: {nickname}"},
    "show_users_no_users_online": {"en": "No users online to select.", "ru": "Нет пользователей онлайн для выбора."},
    "show_users_no_other_users_online": {"en": "No other users online to select.", "ru": "Нет других пользователей онлайн для выбора."},
    "show_users_select_id": {"en": "Select a user to get ID:", "ru": "Выберите пользователя для получения ID:"},
    "show_users_select_kick": {"en": "Select a user to kick:", "ru": "Выберите пользователя для кика:"},
    "show_users_select_ban": {"en": "Select a user to ban:", "ru": "Выберите пользователя для бана:"},
    "show_users_select_default": {"en": "Select a user:", "ru": "Выберите пользователя:"},
    "unknown_command": {"en": "Unknown command. Use /help to see available commands.", "ru": "Неизвестная команда. Используйте /help для просмотра доступных команд."},
    "tt_reply_success": {"en": "Message sent to Telegram successfully.", "ru": "Сообщение успешно отправлено в Telegram."},
    "tt_reply_fail_invalid_token": {"en": "Failed to send message: Invalid token.", "ru": "Не удалось отправить сообщение: неверный токен."},
    "tt_reply_fail_api_error": {"en": "Failed to send message: Telegram API Error: {error}", "ru": "Не удалось отправить сообщение: Ошибка Telegram API: {error}"},
    "tt_reply_fail_generic_error": {"en": "Failed to send message: {error}", "ru": "Не удалось отправить сообщение: {error}"},
    "tt_subscribe_deeplink_text": {"en": "Click this link to subscribe to notifications (link valid for 5 minutes):\n{deeplink_url}", "ru": "Нажмите на эту ссылку, чтобы подписаться на уведомления (ссылка действительна 5 минут):\n{deeplink_url}"},
    "tt_subscribe_error": {"en": "An error occurred while processing the subscription request.", "ru": "Произошла ошибка при обработке запроса на подписку."},
    "tt_unsubscribe_deeplink_text": {"en": "Click this link to unsubscribe from notifications (link valid for 5 minutes):\n{deeplink_url}", "ru": "Нажмите на эту ссылку, чтобы отписаться от уведомлений (ссылка действительна 5 минут):\n{deeplink_url}"},
    "tt_unsubscribe_error": {"en": "An error occurred while processing the unsubscription request.", "ru": "Произошла ошибка при обработке запроса на отписку."},
    "tt_admin_cmd_no_permission": {"en": "You do not have permission to use this command.", "ru": "У вас нет прав на использование этой команды."},
    "tt_add_admin_prompt_ids": {"en": "Please provide Telegram IDs after the command. Example: /add_admin 12345678 98765432", "ru": "Пожалуйста, укажите Telegram ID после команды. Пример: /add_admin 12345678 98765432"},
    "tt_add_admin_success": {"en": "Successfully added {count} admin(s).", "ru": "Успешно добавлено администраторов: {count}."},
    "tt_add_admin_error_already_admin": {"en": "ID {telegram_id} is already an admin or failed to add.", "ru": "ID {telegram_id} уже является администратором или не удалось добавить."},
    "tt_add_admin_error_invalid_id": {"en": "'{telegram_id_str}' is not a valid numeric Telegram ID.", "ru": "'{telegram_id_str}' не является действительным числовым Telegram ID."},
    "tt_admin_errors_header": {"en": "Errors:\n- ", "ru": "Ошибки:\n- "},
    "tt_admin_info_errors_header": {"en": "Info/Errors:\n- ", "ru": "Информация/Ошибки:\n- "},
    "tt_admin_no_valid_ids": {"en": "No valid IDs provided.", "ru": "Не предоставлено действительных ID."},
    "tt_admin_error_processing": {"en": "An error occurred while processing the command.", "ru": "Произошла ошибка при обработке команды."},
    "tt_remove_admin_prompt_ids": {"en": "Please provide Telegram IDs after the command. Example: /remove_admin 12345678 98765432", "ru": "Пожалуйста, укажите Telegram ID после команды. Пример: /remove_admin 12345678 98765432"},
    "tt_remove_admin_success": {"en": "Successfully removed {count} admin(s).", "ru": "Успешно удалено администраторов: {count}."},
    "tt_remove_admin_error_not_found": {"en": "Admin with ID {telegram_id} not found.", "ru": "Администратор с ID {telegram_id} не найден."},
    "tt_noon_usage": {"en": "Usage: /not on online", "ru": "Использование: /not on online"},
    "tt_noon_confirm_deeplink_text": {"en": "To enable 'not on online' notifications for your TeamTalk user '{tt_username}', please open this link in Telegram and confirm (link valid for 5 minutes):\n{deeplink_url}", "ru": "Чтобы включить уведомления 'не в сети' для вашего пользователя TeamTalk '{tt_username}', пожалуйста, откройте эту ссылку в Telegram и подтвердите (ссылка действительна 5 минут):\n{deeplink_url}"},
    "tt_noon_error_processing": {"en": "An error occurred while processing the request.", "ru": "Произошла ошибка при обработке запроса."},
    "tt_unknown_command": {"en": "Unknown command. Available commands: /sub, /unsub, /add_admin, /remove_admin, /not on online, /help.", "ru": "Неизвестная команда. Доступные команды: /sub, /unsub, /add_admin, /remove_admin, /not on online, /help."},
    "tt_forward_message_text": {"en": "Message from server {server_name}\nFrom {sender_display}:\n\n{message_text}", "ru": "Сообщение с сервера {server_name}\nОт {sender_display}:\n\n{message_text}"},
    "join_notification": {"en": "User {user_nickname} joined server {server_name}", "ru": "{user_nickname} присоединился к серверу {server_name}"},
    "leave_notification": {"en": "User {user_nickname} left server {server_name}", "ru": "{user_nickname} покинул сервер {server_name}"},
    "help_text": {
        "en": (
                "This bot forwards messages from a TeamTalk server to Telegram and sends join/leave notifications.\n\n"
                "**Telegram Commands:**\n"
                "/who - Show online users.\n"
                "/id - Get ID of a user (via buttons).\n"
                "/kick - Kick a user from the server (admin, via buttons).\n"
                "/ban - Ban a user from the server (admin, via buttons).\n"
                "/cl `en|ru` - Change bot language.\n"
                "/notify_all - Enable all join/leave notifications.\n"
                "/notify_join_off - Disable join notifications.\n"
                "/notify_leave_off - Disable leave notifications.\n"
                "/notify_none - Disable all join/leave notifications.\n"
                "/start - Start bot or process deeplink.\n"
                "/mute user `<username>` - Add user to mute list (don't receive notifications).\n"
                "/unmute user `<username>` - Remove user from mute list.\n"
                "/mute_all - Enable 'mute all' mode (only get notifications for exceptions in the mute list).\n"
                "/unmute_all - Disable 'mute all' mode (get notifications for everyone except the mute list).\n"
                "/toggle_noon - Toggle silent notifications if your linked TeamTalk user is online.\n"
                "/my_noon_status - Check your 'not on online' feature status.\n"
                "/help - Show this help message.\n\n"
                "**Note on Mutes and 'Toggle ignore status' Buttons:**\n"
                "- The 'Toggle ignore status' button under join/leave messages manages your personal mute list for that TeamTalk user.\n"
                "- When `/mute_all` is **disabled** (default): the mute list contains users you **don't** get notifications from. Pressing the button toggles if the user is in this list.\n"
                "- When `/mute_all` is **enabled**: the mute list contains users you **do** get notifications from (exceptions). Pressing the button toggles if the user is in this exception list.\n"
                "- `/unmute_all` always disables `/mute_all` and clears the list.\n\n"
                "**Note on 'Not on Online' feature (/toggle_noon):**\n"
                "- First, set it up via TeamTalk: `/not on online` in a private message to the TeamTalk bot.\n"
                "- After confirming via the link in Telegram, this feature will be active.\n"
                "- If your linked TeamTalk user is online, Telegram notifications will be silent.\n\n"
                "**TeamTalk Commands (in private message to the bot):**\n"
                "/sub - Get a link to subscribe to notifications.\n"
                "/unsub - Get a link to unsubscribe from notifications.\n"
                "/add_admin `<Telegram ID>` [`<Telegram ID>`...] - Add bot admin (ADMIN_USERNAME from .env only).\n"
                "/remove_admin `<Telegram ID>` [`<Telegram ID>`...] - Remove bot admin (ADMIN_USERNAME from .env only).\n"
                "/not on online - Set up silent notifications for when you are online in TeamTalk.\n"
                "/help - Show help."
        ),
        "ru": (
                "Этот бот пересылает сообщения с TeamTalk сервера в Telegram и уведомляет о входе/выходе пользователей.\n\n"
                "**Команды Telegram:**\n"
                "/who - Показать онлайн пользователей.\n"
                "/id - Получить ID пользователя (через кнопки).\n"
                "/kick - Кикнуть пользователя с сервера (админ, через кнопки).\n"
                "/ban - Забанить пользователя на сервере (админ, через кнопки).\n"
                "/cl `en|ru` - Изменить язык бота.\n"
                "/notify_all - Включить все уведомления.\n"
                "/notify_join_off - Выключить уведомления о входах.\n"
                "/notify_leave_off - Выключить уведомления о выходах.\n"
                "/notify_none - Выключить все уведомления.\n"
                "/start - Запустить бота или обработать deeplink.\n"
                "/mute user `<username>` - Добавить пользователя в список мьюта (не получать уведомления).\n"
                "/unmute user `<username>` - Удалить пользователя из списка мьюта.\n"
                '/mute_all - Включить режим "мьют всех" (уведомления только для исключений из списка мьюта).\n'
                '/unmute_all - Выключить режим "мьют всех" (уведомления для всех, кроме списка мьюта).\n'
                "/toggle_noon - Включить/выключить тихие уведомления, если связанный пользователь TeamTalk онлайн.\n"
                "/my_noon_status - Проверить статус функции 'не в сети'.\n"
                "/help - Показать это сообщение.\n\n"
                "**Примечание по мьютам и кнопкам 'Переключить статус игнорирования':**\n"
                "- Кнопка 'Переключить статус игнорирования' под сообщениями о входе/выходе управляет вашим персональным списком мьюта для этого пользователя TeamTalk.\n"
                "- Когда `/mute_all` **выключен** (по умолчанию): список мьюта содержит тех, от кого **не** приходят уведомления. Нажатие кнопки переключает, будет ли пользователь в этом списке.\n"
                "- Когда `/mute_all` **включен**: список мьюта содержит тех, от кого **приходят** уведомления (исключения). Нажатие кнопки переключает, будет ли пользователь в этом списке исключений.\n"
                "- `/unmute_all` всегда выключает `/mute_all` и очищает список.\n\n"
                "**Примечание по функции 'не в сети' (/toggle_noon):**\n"
                "- Сначала настройте через TeamTalk: `/not on online` в личные сообщения боту TeamTalk.\n"
                "- После подтверждения по ссылке в Telegram, эта функция будет активна.\n"
                "- Если связанный пользователь TeamTalk онлайн, уведомления в Telegram будут приходить без звука.\n\n"
                "**Команды TeamTalk (в личные сообщения боту):**\n"
                "/sub - Получить ссылку для подписки на уведомления.\n"
                "/unsub - Получить ссылку для отписки от уведомлений.\n"
                "/add_admin `<Telegram ID>` [`<Telegram ID>`...] - Добавить админа бота (только для ADMIN_USERNAME из .env).\n"
                "/remove_admin `<Telegram ID>` [`<Telegram ID>`...] - Удалить админа бота (только для ADMIN_USERNAME из .env).\n"
                "/not on online - Настроить тихие уведомления, когда вы онлайн в TeamTalk.\n"
                "/help - Показать справку."
        ),
    },
}

def get_text(key: str, lang: str, **kwargs) -> str:
    lookup_key = key.lower()

    message_template = LOCALIZED_STRINGS.get(lookup_key, {}).get(lang)
    if message_template is None:
        effective_default_lang = app_config["EFFECTIVE_DEFAULT_LANG"] # Assumes EFFECTIVE_DEFAULT_LANG is always set
        default_lang_template = LOCALIZED_STRINGS.get(lookup_key, {}).get(effective_default_lang)
        if default_lang_template is not None:
            message_template = default_lang_template
        else:
            logger.warning(f"Localization key '{key}' (tried as '{lookup_key}') not found for lang '{lang}' or default lang '{effective_default_lang}'.")
            message_template = f"[{key}_{lang}]"

    try:
        return message_template.format(**kwargs)
    except KeyError as e:
        logger.warning(f"Missing placeholder {e} for key '{lookup_key}' (original: '{key}') in lang '{lang}' with kwargs {kwargs}")
        return message_template
    except Exception as e_format:
        logger.error(f"Error formatting string for key '{lookup_key}' (original: '{key}'), lang '{lang}', kwargs {kwargs}: {e_format}")
        return f"[FORMAT_ERROR:{lookup_key}_{lang}]"
        