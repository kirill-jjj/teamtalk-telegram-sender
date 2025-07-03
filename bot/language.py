import gettext
from pathlib import Path
from bot.core.languages import DEFAULT_LANGUAGE_CODE

LOCALE_DIR = Path(__file__).parent.parent.joinpath("locales")
DOMAIN = "messages"

# Cache for loaded translators to avoid repeated file I/O
_TRANSLATOR_CACHE: dict[str, gettext.GNUTranslations] = {}

def get_translator(language_code: str = DEFAULT_LANGUAGE_CODE) -> gettext.GNUTranslations:
    """
    Returns a translator object for the specified language code.
    Caches translators after first load.
    Falls back to DEFAULT_LANGUAGE_CODE if the requested language is not found
    or if the default language itself fails to load (in which case NullTranslations is used).
    """
    if language_code in _TRANSLATOR_CACHE:
        return _TRANSLATOR_CACHE[language_code]

    try:
        translation = gettext.translation(DOMAIN, localedir=LOCALE_DIR, languages=[language_code])
        _TRANSLATOR_CACHE[language_code] = translation
        return translation
    except FileNotFoundError:
        # If requested language is not found, try falling back to default
        if language_code != DEFAULT_LANGUAGE_CODE:
            print(f"Warning: Language '{language_code}' not found. Falling back to default '{DEFAULT_LANGUAGE_CODE}'.")
            return get_translator(DEFAULT_LANGUAGE_CODE) # Recursive call for default
        else:
            # If default language itself is not found, use NullTranslations
            print(f"Error: Default language '{DEFAULT_LANGUAGE_CODE}' not found. Using NullTranslations.")
            null_trans = gettext.NullTranslations()
            _TRANSLATOR_CACHE[language_code] = null_trans # Cache NullTranslations for this code
            return null_trans
