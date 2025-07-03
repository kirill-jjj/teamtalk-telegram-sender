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

AVAILABLE_LANGUAGES_DATA: List[LanguageInfo] = []

def discover_languages(locales_path: str = _LOCALE_DIR) -> List[LanguageInfo]:
    """
    Scans the locales directory to find available languages and their native names.
    A language is considered available if a subdirectory with its code exists
    and contains the compiled LC_MESSAGES/messages.mo file,
    and if its messages.po contains a translation for "language_native_name".
    """
    discovered: List[LanguageInfo] = []
    if not os.path.isdir(locales_path):
        # Log an error or handle missing locales directory
        print(f"Error: Locales directory not found at {locales_path}")
        return discovered

    for lang_code in os.listdir(locales_path):
        lang_path = os.path.join(locales_path, lang_code)
        mo_file_path = os.path.join(lang_path, "LC_MESSAGES", "messages.mo")

        if os.path.isdir(lang_path) and os.path.isfile(mo_file_path):
            native_name = lang_code # Default to lang_code
            try:
                # Temporarily load translator for this language to get its native name
                # Note: gettext.translation might be slow if called many times.
                # Consider optimizing if startup time becomes an issue with many languages.
                translator = gettext.translation(
                    "messages", localedir=locales_path, languages=[lang_code]
                )
                # Ensure the translator is activated for the current thread context
                # translator.install() # Not ideal here as it might affect global state
                # Instead, directly use the gettext method from the translator object
                native_name_translated = translator.gettext("language_native_name")
                if native_name_translated and native_name_translated != "language_native_name":
                    native_name = native_name_translated
                else:
                    print(f"Warning: 'language_native_name' not translated for {lang_code}, using code as name.")
            except FileNotFoundError:
                # This means .mo file was found by os.path.isfile but gettext couldn't load it.
                # This shouldn't typically happen if the .mo check passes.
                print(f"Warning: Could not load translations for {lang_code} despite .mo file presence.")
            except Exception as e:
                # Catch other potential errors during gettext loading or translation
                print(f"Error loading native name for {lang_code}: {e}")

            discovered.append({"code": lang_code, "native_name": native_name})

    # Ensure default language is present if discovered, or add it manually as a fallback
    if not any(lang['code'] == DEFAULT_LANGUAGE_CODE for lang in discovered):
        # This fallback assumes English is always available and its native name is "English"
        # It's better if "en" is always properly discovered via its .po file.
        print(f"Warning: Default language '{DEFAULT_LANGUAGE_CODE}' not discovered. Adding manually.")
        discovered.append({"code": DEFAULT_LANGUAGE_CODE, "native_name": "English"}) # Fallback native name

    # Sort languages by native name for consistent display in UI
    discovered.sort(key=lambda x: x["native_name"])

    return discovered

