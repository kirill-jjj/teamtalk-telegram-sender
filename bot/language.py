import gettext
from pathlib import Path

LOCALE_DIR = Path(__file__).parent.joinpath("locales")
DOMAIN = "messages"

def get_translator(lang_code: str = "en") -> gettext.GNUTranslations:
    """
    Returns a translator object for the specified language.
    If a translation is not found, returns NullTranslations, which
    will simply return the original string as is.
    """
    try:
        translation = gettext.translation(DOMAIN, localedir=LOCALE_DIR, languages=[lang_code])
    except FileNotFoundError:
        translation = gettext.NullTranslations()

    return translation
