import os
import gettext
from typing import List, Dict, TypedDict

# Define a path to the locales directory relative to this file or project root
# Assuming project root is parent of 'bot' directory
# For robustness, this might need to be derived from app_config or a known structure
_LOCALE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "locales")

DEFAULT_LANGUAGE_CODE = "en" # Default language

class LanguageInfo(TypedDict):
    code: str
    native_name: str


def discover_languages(locales_path: str = _LOCALE_DIR) -> List[LanguageInfo]:
    """
    Scans the locales directory for translated languages and always includes English as the base language.
    """
    # 1. Начинаем список с английского языка, который является исходным.
    #    Его нативное имя - это не "перевод", а метаданные.
    discovered: List[LanguageInfo] = [
        {"code": DEFAULT_LANGUAGE_CODE, "native_name": "English"}
    ]

    discovered_codes = {DEFAULT_LANGUAGE_CODE}

    if not os.path.isdir(locales_path):
        print(f"Warning: Locales directory not found at {locales_path}. Only English will be available.")
        return discovered

    # 2. Ищем и добавляем все остальные переведенные языки.
    for lang_code in os.listdir(locales_path):
        if lang_code in discovered_codes:
            continue # Пропускаем, если это 'en' (которого уже не должно быть)

        lang_path = os.path.join(locales_path, lang_code)
        mo_file_path = os.path.join(lang_path, "LC_MESSAGES", "messages.mo")

        if os.path.isdir(lang_path) and os.path.isfile(mo_file_path):
            native_name = lang_code
            try:
                translator = gettext.translation(
                    "messages", localedir=locales_path, languages=[lang_code]
                )
                native_name_translated = translator.gettext("language_native_name")
                if native_name_translated and native_name_translated != "language_native_name":
                    native_name = native_name_translated
                else:
                    print(f"Warning: 'language_native_name' not translated for {lang_code}, using code as name.")
            except Exception as e:
                print(f"Warning: Could not load native name for {lang_code}: {e}")

            discovered.append({"code": lang_code, "native_name": native_name})
            discovered_codes.add(lang_code)

    # 3. Сортируем итоговый список для красивого отображения в меню.
    discovered.sort(key=lambda x: x["native_name"])

    return discovered

