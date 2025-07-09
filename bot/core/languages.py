"""Language and localization utilities."""

import gettext
import logging
from pathlib import Path  # Added for Path operations
from typing import TypedDict

logger = logging.getLogger(__name__)

# Define a path to the locales directory relative to this file or project root
# Assuming project root is parent of 'bot' directory
# For robustness, this might need to be derived from app_config or a known structure
_LOCALE_DIR = Path(__file__).resolve().parent.parent.parent / "locales"

DEFAULT_LANGUAGE_CODE = "en"


class LanguageInfo(TypedDict):
    """Represents information about a discovered language."""

    code: str
    native_name: str


def discover_languages(locales_path: Path = _LOCALE_DIR) -> list[LanguageInfo]:
    """Scans the locales directory for translated languages and always includes English as the base language."""
    # 1. Start the list with English, which is the source language.
    #    Its native name is not a "translation" but metadata.
    discovered: list[LanguageInfo] = [{"code": DEFAULT_LANGUAGE_CODE, "native_name": "English"}]

    discovered_codes = {DEFAULT_LANGUAGE_CODE}

    locales_path_obj = Path(locales_path)  # Convert to Path object
    if not locales_path_obj.is_dir():
        logger.warning("Locales directory not found at %s. Only English will be available.", locales_path)
        return discovered

    # 2. Search for and add all other translated languages.
    for lang_code_path in locales_path_obj.iterdir():  # Use Path.iterdir()
        lang_code = lang_code_path.name  # Get the directory name as lang_code
        if lang_code in discovered_codes:
            continue

        # lang_path is already lang_code_path
        mo_file_path = lang_code_path / "LC_MESSAGES" / "messages.mo"  # Use / operator

        if lang_code_path.is_dir() and mo_file_path.is_file():  # Use Path methods
            native_name = lang_code
            try:
                translator = gettext.translation("messages", localedir=str(locales_path_obj), languages=[lang_code])
                native_name_translated = translator.gettext("language_native_name")
                if native_name_translated and native_name_translated != "language_native_name":
                    native_name = native_name_translated
                else:
                    logger.warning("'language_native_name' not translated for %s, using code as name.", lang_code)
            except Exception as e:
                logger.warning("Could not load native name for %s: %s", lang_code, e)

            discovered.append({"code": lang_code, "native_name": native_name})
            discovered_codes.add(lang_code)

    # 3. Sort the final list for nice display in menus.
    discovered.sort(key=lambda x: x["native_name"])

    return discovered
