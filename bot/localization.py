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
    "noon_toggled_enabled": {"en": "'Not on online' notifications are now ENABLED for TeamTalk user '{tt_username}'. You will receive silent notifications when this user is online.", "ru": "Функция 'не в сети' теперь ВКЛЮЧЕНА для пользователя TeamTalk '{tt_username}'. Вы будете получать тихие уведомления, когда этот пользователь будет в сети."},
    "noon_toggled_disabled": {"en": "'Not on online' notifications are now DISABLED for TeamTalk user '{tt_username}'. Notifications will be sent normally.", "ru": "Функция 'не в сети' теперь ВЫКЛЮЧЕНА для пользователя TeamTalk '{tt_username}'. Уведомления будут приходить как обычно."},
    "noon_error_updating": {"en": "Error updating settings. Please try again.", "ru": "Ошибка обновления настроек. Пожалуйста, попробуйте снова."},
    "noon_status_not_configured": {"en": "'Not on online' feature is not configured for your account. Use `/not on online` in TeamTalk to set it up.", "ru": "Функция 'не в сети' не настроена для вашего аккаунта. Используйте `/not on online` в TeamTalk для настройки."},
    "noon_status_report": {"en": "'Not on online' notifications are {status} for TeamTalk user '{tt_username}'.", "ru": "Функция 'не в сети' {status} для пользователя TeamTalk '{tt_username}'."},
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
    "tt_add_admin_error_already_admin": {"en": "ID {telegram_id} is already an admin or failed to add.", "ru": "ID {telegram_id} уже является администратором, или не удалось его добавить."},
    "tt_add_admin_error_invalid_id": {"en": "'{telegram_id_str}' is not a valid numeric Telegram ID.", "ru": "'{telegram_id_str}' не является действительным числовым Telegram ID."},
    "tt_admin_errors_header": {"en": "Errors:\n- ", "ru": "Ошибки:\n- "},
    "tt_admin_info_errors_header": {"en": "Info/Errors:\n- ", "ru": "Информация/Ошибки:\n- "},
    "tt_admin_no_valid_ids": {"en": "No valid IDs provided.", "ru": "Не предоставлено действительных ID."},
    "tt_admin_error_processing": {"en": "An error occurred while processing the command.", "ru": "Произошла ошибка при обработке команды."},
    "tt_remove_admin_prompt_ids": {"en": "Please provide Telegram IDs after the command. Example: /remove_admin 12345678 98765432", "ru": "Пожалуйста, укажите Telegram ID после команды. Пример: /remove_admin 12345678 98765432"},
    "tt_remove_admin_success": {"en": "Successfully removed {count} admin(s).", "ru": "Успешно удалено администраторов: {count}."},
    "tt_remove_admin_error_not_found": {"en": "Admin with ID {telegram_id} not found.", "ru": "Администратор с ID {telegram_id} не найден."},
    "tt_noon_error_processing": {"en": "An error occurred while processing the request.", "ru": "Произошла ошибка при обработке запроса."},
    "tt_unknown_command": {"en": "Unknown command. Available commands: /sub, /unsub, /add_admin, /remove_admin, /help.", "ru": "Неизвестная команда. Доступные команды: /sub, /unsub, /add_admin, /remove_admin, /help."},
    "tt_forward_message_text": {"en": "Message from server {server_name}\nFrom {sender_display}:\n\n{message_text}", "ru": "Сообщение с сервера {server_name}\nОт {sender_display}:\n\n{message_text}"},
    "join_notification": {"en": "User {user_nickname} joined server {server_name}", "ru": "{user_nickname} присоединился к серверу {server_name}"},
    "leave_notification": {"en": "User {user_nickname} left server {server_name}", "ru": "{user_nickname} покинул сервер {server_name}"},
    "help_text": {
        "en": (
                "This bot forwards messages from a TeamTalk server to Telegram and sends join/leave notifications.\n\n"
                "**Available Commands:**\n"
                "/who - Show online users.\n"
                "/settings - Access the interactive settings menu (language, notifications, mute lists, NOON feature).\n"
                "/help - Show this help message.\n"
                "(Note: `/start` is used to initiate the bot and process deeplinks.)\n\n"
                "**Admin Commands:**\n"
                "/kick - Kick a user from the server (via buttons).\n"
                "/ban - Ban a user from the server (via buttons).\n\n"
                "**Note on Mutes:**\n"
                "- Mute functionality (block list / allow list) is managed via the `/settings` menu.\n\n"
                "**Note on 'Not on Online' (NOON) feature (via /settings):**\n"
                "- This feature is activated by using the `/sub` command in a private message to the TeamTalk bot. This links your TeamTalk account.\n"
                "- Once linked, the NOON feature can be managed in Telegram under `/settings`.\n"
                "- If your linked TeamTalk user is online, Telegram notifications will be silent if NOON is enabled.\n\n"
                "**TeamTalk Commands (in private message to the bot):**\n"
                "/sub - Get a link to subscribe to notifications and link your TeamTalk account for NOON.\n"
                "/unsub - Get a link to unsubscribe from notifications.\n"
                "/add_admin `<Telegram ID>` [`<Telegram ID>`...] - Add bot admin (MAIN_ADMIN from config only).\n"
                "/remove_admin `<Telegram ID>` [`<Telegram ID>`...] - Remove bot admin (MAIN_ADMIN from config only).\n"
                "/help - Show help."
        ),
        "ru": (
                "Этот бот пересылает сообщения с TeamTalk сервера в Telegram и уведомляет о входе/выходе пользователей.\n\n"
                "**Доступные команды:**\n"
                "/who - Показать онлайн пользователей.\n"
                "/settings - Доступ к интерактивному меню настроек (язык, уведомления, списки мьютов, функция NOON).\n"
                "/help - Показать это сообщение.\n"
                "(Примечание: `/start` используется для запуска бота и обработки deeplink-ссылок.)\n\n"
                "**Команды для администраторов:**\n"
                "/kick - Кикнуть пользователя с сервера (через кнопки).\n"
                "/ban - Забанить пользователя на сервере (через кнопки).\n\n"
                "**Примечание по мьютам:**\n"
                "- Управление мьютами (черный/белый список) осуществляется через меню `/settings`.\n\n"
                "**Примечание по функции 'не в сети' (NOON) (через /settings):**\n"
                "- Эта функция активируется использованием команды `/sub` в личных сообщениях боту TeamTalk. Это связывает ваш аккаунт TeamTalk.\n"
                "- После связывания, функцией NOON можно управлять в Telegram через `/settings`.\n"
                "- Если связанный пользователь TeamTalk онлайн, уведомления в Telegram будут приходить без звука, если функция NOON включена.\n\n"
                "**Команды TeamTalk (в личные сообщения боту):**\n"
                "/sub - Получить ссылку для подписки на уведомления и связать ваш аккаунт TeamTalk для NOON.\n"
                "/unsub - Получить ссылку для отписки от уведомлений.\n"
                "/add_admin `<Telegram ID>` [`<Telegram ID>`...] - Добавить админа бота (только для ГЛАВНОГО АДМИНА из конфигурации).\n"
                "/remove_admin `<Telegram ID>` [`<Telegram ID>`...] - Удалить админа бота (только для ГЛАВНОГО АДМИНА из конфигурации).\n"
                "/help - Показать справку."
        ),
    },
    "settings_menu_header": {"en": "⚙️ Settings", "ru": "⚙️ Настройки"},
    "settings_btn_language": {"en": "Language", "ru": "Язык"},
    "settings_btn_subscriptions": {"en": "Subscription Settings", "ru": "Настройки подписок"},
    "settings_btn_notifications": {"en": "Notification Settings", "ru": "Настройки уведомлений"},
    "choose_language_prompt": {"en": "Please choose your language:", "ru": "Пожалуйста, выберите ваш язык:"},
    "language_btn_en": {"en": "English", "ru": "English"}, # Russian value is "English" as it's the name of the language
    "language_btn_ru": {"en": "Русский", "ru": "Русский"}, # English value is "Русский" as it's the name of the language
    "language_updated_to": {"en": "Language updated to {lang_name}.", "ru": "Язык обновлен на {lang_name}."},
    "subs_settings_menu_header": {"en": "Subscription Settings", "ru": "Настройки подписок"},
    "subs_setting_all_btn": {"en": "All (Join & Leave)", "ru": "Все (Вход и выход)"},
    "subs_setting_join_only_btn": {"en": "Join Only", "ru": "Только вход"},
    "subs_setting_leave_only_btn": {"en": "Leave Only", "ru": "Только выход"},
    "subs_setting_none_btn": {"en": "None", "ru": "Никакие"},
    "subs_setting_updated_to": {"en": "Subscription setting updated to: {setting_name}", "ru": "Настройка подписок обновлена на: {setting_name}"},
    "active_choice_marker": {"en": "✅ ", "ru": "✅ "},
    "back_to_settings_btn": {"en": "⬅️ Back to Settings", "ru": "⬅️ Назад к настройкам"},
    "notif_settings_menu_header": {"en": "Notification Settings", "ru": "Настройки уведомлений"},
    "notif_setting_noon_btn_toggle": {"en": "NOON (Not on Online): {status}", "ru": "NOON (Не в сети): {status}"},
    "notif_setting_noon_btn_setup_required": {"en": "NOON (Setup Required via TeamTalk)", "ru": "NOON (Требуется настройка через TeamTalk)"},
    "notif_setting_noon_setup_required_alert": {"en": "NOON feature requires your TeamTalk account to be linked. Use the `/sub` command in a private message to the TeamTalk bot to subscribe and link your account.", "ru": "Функция NOON требует связывания вашего аккаунта TeamTalk. Используйте команду `/sub` в личных сообщениях боту TeamTalk, чтобы подписаться и связать ваш аккаунт."},
    "notif_setting_manage_muted_btn": {"en": "Manage Muted/Allowed Users", "ru": "Управление блокировками"},
    "notif_setting_noon_updated_to": {"en": "NOON (Not on Online) is now {status}.", "ru": "NOON (Не в сети) теперь {status}."},
    "enabled_status": {"en": "Enabled", "ru": "Включено"},
    "disabled_status": {"en": "Disabled", "ru": "Выключено"},
    "manage_muted_menu_header": {"en": "Manage Muted/Allowed Users", "ru": "Управление блокировками пользователей"},
    "mute_all_btn_toggle": {"en": "Mute All Mode: {status}", "ru": "Режим \"Блокировать всех\": {status}"},
    "mute_all_updated_to": {"en": "Mute All Mode is now {status}.", "ru": "Режим \"Блокировать всех\" теперь {status}."},
    "list_muted_users_btn": {"en": "View Muted Users (Block List)", "ru": "Просмотр заблокированных (Черный список)"},
    "list_allowed_users_btn": {"en": "View Allowed Users (Allow List)", "ru": "Просмотр разрешенных (Белый список)"},
    "mute_from_server_list_btn": {"en": "Mute/Unmute from Server List", "ru": "Блокировать/Разблокировать из списка сервера"},
    "back_to_notif_settings_btn": {"en": "⬅️ Back to Notification Settings", "ru": "⬅️ Назад к настройкам уведомлений"},
    "muted_users_list_header": {"en": "Muted Users (Block List):", "ru": "Заблокированные пользователи (Черный список):"},
    "allowed_users_list_header": {"en": "Allowed Users (Allow List):", "ru": "Разрешенные пользователи (Белый список):"},
    "no_muted_users_found": {"en": "No users are currently muted.", "ru": "Сейчас нет заблокированных пользователей."},
    "no_allowed_users_found": {"en": "No users are currently in the allow list.", "ru": "Сейчас нет пользователей в белом списке."},
    "unmute_user_btn": {"en": "Unmute {username}", "ru": "Разблокировать {username}"},
    "mute_user_btn": {"en": "Mute {username}", "ru": "Заблокировать {username}"},
    "page_indicator": {"en": "Page {current_page}/{total_pages}", "ru": "Страница {current_page}/{total_pages}"},
    "pagination_prev_btn": {"en": "⬅️ Prev", "ru": "⬅️ Назад"},
    "pagination_next_btn": {"en": "Next ➡️", "ru": "Вперед ➡️"},
    "back_to_manage_muted_btn": {"en": "⬅️ Back to Mute Management", "ru": "⬅️ Назад к управлению блокировками"},
    "user_unmuted_toast": {"en": "{username} has been unmuted.", "ru": "{username} был разблокирован."},
    "user_muted_toast": {"en": "{username} has been muted.", "ru": "{username} был заблокирован."},
    "all_accounts_list_header": {"en": "Mute/Unmute - All Server Accounts:", "ru": "Блокировка/Разблокировка - Все аккаунты сервера:"}, # Renamed from SERVER_USER_LIST_HEADER
    "no_server_accounts_found": {"en": "No user accounts found on the server.", "ru": "Учетные записи на сервере не найдены."}, # Renamed from NO_SERVER_USERS_FOUND
    "toggle_mute_status_btn": {"en": "{username} (Status: {current_status})", "ru": "{username} (Статус: {current_status})"}, # This can remain if {username} is general enough
    "muted_status": {"en": "Muted", "ru": "Заблокирован"},
    "not_muted_status": {"en": "Not Muted", "ru": "Не заблокирован"},
    "user_mute_status_updated_toast": {"en": "Mute status for {username} is now {status}.", "ru": "Статус блокировки для {username} теперь {status}."},
    "tt_bot_not_connected_for_list": {"en": "TeamTalk bot is not connected. Cannot fetch server users.", "ru": "Бот TeamTalk не подключен. Невозможно получить список пользователей сервера."},
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
        