import polib

def update_po_file(filepath, translations_to_update):
    try:
        po = polib.pofile(filepath)
    except Exception as e:
        print(f"Error reading or parsing .po file: {e}")
        return False

    found_ids = set()
    updated_count = 0

    for entry in po:
        if entry.msgid in translations_to_update:
            found_ids.add(entry.msgid)
            new_msgstr = translations_to_update[entry.msgid]

            # Check if an update is needed
            needs_update = False
            if entry.msgstr != new_msgstr:
                needs_update = True
            if 'fuzzy' in entry.flags:
                needs_update = True
            if entry.previous_msgid is not None or entry.previous_msgid_plural is not None: # Indicates #| lines
                needs_update = True

            if needs_update:
                entry.msgstr = new_msgstr
                if 'fuzzy' in entry.flags:
                    entry.flags.remove('fuzzy')
                entry.previous_msgid = None
                entry.previous_msgid_plural = None
                entry.previous_comment = None
                updated_count +=1
            elif entry.msgstr == new_msgstr and not entry.obsolete:
                 pass


    for msgid in translations_to_update:
        if msgid not in found_ids:
            print(f"Warning: msgid '{msgid}' not found in .po file.")

    if updated_count > 0:
        try:
            po.save(filepath)
            print(f"Successfully updated {updated_count} entries in {filepath}")
        except Exception as e:
            print(f"Error saving .po file: {e}")
            return False
    else:
        print(f"No strings needed explicit updating in {filepath} based on provided translations (already correct or not found).")

    # Log which msgids were processed for clarity, even if no change was made to them
    # because they were already correct.
    if found_ids:
        print(f"Processed {len(found_ids)} matching msgids from the input list.")

    # Consider the operation successful if no file I/O errors occurred,
    # even if some msgids were not found or didn't need updating.
    # The warnings for not-found msgids serve as important feedback.
    return True

translations = {
    "Russian": "Русский",
    "Unmute {username}": "Разблокировать {username}",
    "Mute {username}": "Заблокировать {username}",
    "Muted": "Заблокирован",
    "Not Muted": "Не заблокирован",
    "Settings": "Настройки",
    "The bot lacks permissions on the TeamTalk server to perform this action.": "У бота недостаточно прав на сервере TeamTalk для выполнения этого действия.",
    "An error occurred during the action on the user: {error}": "Произошла ошибка при действии с пользователем: {error}",
    "Success!": "Успешно!",
    "Muted Users (Block List)": "Заблокированные пользователи (Черный список)",
    "You haven't muted anyone yet.": "Вы еще никого не заблокировали.",
    "Allowed Users (Allow List)": "Разрешенные пользователи (Белый список)",
    "No users are currently on the allow list.": "В белом списке пока нет пользователей.",
    "An error occurred. Please try again later.": "Произошла ошибка. Пожалуйста, попробуйте позже.",
    "Server user accounts are not loaded yet. Please try again in a moment.": "Учетные записи пользователей сервера еще не загружены. Пожалуйста, попробуйте через мгновение.",
    "All Server Accounts": "Все учетные записи сервера",
    "No user accounts found on the server.": "Учетные записи на сервере не найдены.",
    "muted (due to Mute All mode)": 'заблокирован (режим "Блокировать всех")',
    "muted": "заблокирован",
    "allowed (in Mute All mode)": 'разрешен (режим "Блокировать всех")',
    "unmuted": "разблокирован",
    "{username} is now {status}.": "{username} теперь {status}.",
    "TeamTalk bot is disconnected. UI could not be refreshed.": "Бот TeamTalk отключен. Интерфейс не может быть обновлен.",
    "Error: Missing data for Mute All toggle.": 'Ошибка: Отсутствуют данные для переключения режима "Блокировать всех".',
    "Mute All mode is now {status}.": 'Режим "Блокировать всех" теперь {status}.',
    "TeamTalk bot is not connected. Cannot display user list.": "Бот TeamTalk не подключен. Невозможно отобразить список пользователей.",
    "Error: No Telegram ID specified for deletion.": "Ошибка: Не указан Telegram ID для удаления."
}

po_file_path = "bot/locales/ru/LC_MESSAGES/messages.po"

if __name__ == "__main__":
    if not update_po_file(po_file_path, translations):
        # Optionally, exit with an error code if critical errors occurred
        # import sys
        # sys.exit(1)
        pass
