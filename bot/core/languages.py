"""Language and localization utilities."""

import gettext
import logging
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOCALE_DIR = _PROJECT_ROOT / "locales"
DOMAIN = "messages"
DEFAULT_LANGUAGE_CODE = "en"


class LanguageInfo(TypedDict):
    """Represents information about a discovered language."""

    code: str
    native_name: str


def discover_languages(locales_path: Path = LOCALE_DIR) -> list[LanguageInfo]:
    """Scan the locales directory for translated languages.

    Always includes English as the base language.
    """
    # 1. Start the list with English, which is the source language.
    #    Its native name is not a "translation" but metadata.
    discovered: list[LanguageInfo] = [
        {"code": DEFAULT_LANGUAGE_CODE, "native_name": "English"}
    ]

    discovered_codes = {DEFAULT_LANGUAGE_CODE}

    locales_path_obj = Path(locales_path)
    if not locales_path_obj.is_dir():
        logger.warning(
            "Locales directory not found at %s. Only English will be available.",
            locales_path,
        )
        return discovered

    # 2. Search for and add all other translated languages.
    for lang_code_path in locales_path_obj.iterdir():
        lang_code = lang_code_path.name
        if lang_code in discovered_codes:
            continue

        mo_file_path = lang_code_path / "LC_MESSAGES" / "messages.mo"

        if lang_code_path.is_dir() and mo_file_path.is_file():
            native_name = lang_code
            try:
                translator = gettext.translation(
                    "messages", localedir=str(locales_path_obj), languages=[lang_code]
                )
                native_name_translated = translator.gettext("language_native_name")
                if (
                    native_name_translated
                    and native_name_translated != "language_native_name"
                ):
                    native_name = native_name_translated
                else:
                    logger.warning(
                        "'language_native_name' not translated for %s, using code "
                        "as name.",
                        lang_code,
                    )
            except (OSError, ValueError) as e:
                logger.warning("Could not load native name for %s: %s", lang_code, e)

            discovered.append({"code": lang_code, "native_name": native_name})
            discovered_codes.add(lang_code)

    # 3. Sort the final list for nice display in menus.
    discovered.sort(key=lambda x: x["native_name"])

    return discovered
