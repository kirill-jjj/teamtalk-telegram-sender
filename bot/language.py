import gettext
from pathlib import Path

LOCALE_DIR = Path(__file__).parent.joinpath("locales")
DOMAIN = "messages"

def get_translator(lang_code: str = "en") -> gettext.GNUTranslations:
    """
    Возвращает объект-переводчик для указанного языка.
    Если перевод не найден, возвращает NullTranslations, который
    будет просто возвращать исходную строку как есть.
    """
    try:
        translation = gettext.translation(DOMAIN, localedir=LOCALE_DIR, languages=[lang_code])
    except FileNotFoundError:
        translation = gettext.NullTranslations()

    return translation
