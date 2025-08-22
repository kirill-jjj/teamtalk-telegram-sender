"""Manage localization files using pybabel for extraction, updates, and compilation."""

#!/usr/bin/env python3
from pathlib import Path
import subprocess
import sys
import tomllib

if sys.platform == "win32":
    import shutil

    # Set console encoding to UTF-8 for Windows
    # This might not be strictly necessary if sys.stdout.reconfigure works,
    # but it's a common practice for Windows console output.
    if chcp_path := shutil.which("chcp"):
        subprocess.run(
            [chcp_path, "65001"],
            capture_output=True,
            check=False,
        )

    # Reconfigure stdout and stderr to use UTF-8
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

PROJECT_NAME = "teamtalk-telegram-sender"
COPYRIGHT_HOLDER = "kirill-jjj"
BABEL_CONFIG = "babel.cfg"
LOCALE_DOMAIN = "messages"

try:
    # Correct BASE_DIR to be the project root (parent of the 'scripts' directory)
    BASE_DIR = Path(__file__).resolve().parent.parent
    LOCALE_DIR = BASE_DIR / "locales"  # Now relative to project root
    POT_FILE = LOCALE_DIR / f"{LOCALE_DOMAIN}.pot"
except NameError:  # Fallback for __file__ not defined
    BASE_DIR = Path.cwd()  # If run directly from project root, cwd() is fine
    LOCALE_DIR = BASE_DIR / "locales"
    POT_FILE = LOCALE_DIR / f"{LOCALE_DOMAIN}.pot"


def get_project_version() -> str:
    """Reads the version from pyproject.toml."""
    pyproject_path = BASE_DIR / "pyproject.toml"
    try:
        with pyproject_path.open("rb") as f:
            data = tomllib.load(f)
        # Assuming version is under [project][version]
        version = data.get("project", {}).get("version")
        if version:
            return str(version)
        print(
            "⚠️ Warning: Version not found in pyproject.toml under project.version.",
            file=sys.stderr,
        )
    except FileNotFoundError:
        print(
            f"⚠️ Warning: pyproject.toml not found at {pyproject_path}. "
            f"Cannot determine project version.",
            file=sys.stderr,
        )
        return "0.0.0"  # Fallback version
    # Broader catch for TOML issues or structure changes
    except (tomllib.TOMLDecodeError, KeyError, AttributeError, TypeError) as e:
        print(
            f"⚠️ Warning: Could not read version from pyproject.toml: {e}",
            file=sys.stderr,
        )
        return "0.0.0"  # Fallback version
    else:
        # and no exception occurred.
        return "0.0.0"  # Fallback version


def extract() -> None:
    """Extracts translatable strings from source code into a .pot template file."""
    version = get_project_version()
    command = [
        "pybabel",
        "extract",
        "-F",
        str(BASE_DIR / BABEL_CONFIG),
        "-o",
        str(POT_FILE),
        f"--project={PROJECT_NAME}",
        f"--version={version}",
        f"--copyright-holder={COPYRIGHT_HOLDER}",
        # Assuming source files are scanned from BASE_DIR
        ".",
    ]
    print(f"--- Executing: {' '.join(command)}")
    try:
        subprocess.run(
            command, check=True, cwd=BASE_DIR, text=True, capture_output=True
        )
        print(f"✅ Messages extracted to '{POT_FILE.relative_to(BASE_DIR)}'")
    except FileNotFoundError:
        print(
            "❌ Error: Command 'pybabel' not found. "
            "Make sure Babel is installed and in your PATH.",
            file=sys.stderr,
        )
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"❌ Error executing 'pybabel extract': {e.stderr}", file=sys.stderr)
        sys.exit(e.returncode)


def update() -> None:
    """Updates existing .po translation files from the .pot template file."""
    extract()
    command = [
        "pybabel",
        "update",
        "-i",
        str(POT_FILE),
        "-d",
        str(LOCALE_DIR),
        "-D",
        LOCALE_DOMAIN,
        "--previous",  # Use .po~ backup files
    ]
    print(f"--- Executing: {' '.join(command)}")
    try:
        subprocess.run(
            command, check=True, cwd=BASE_DIR, text=True, capture_output=True
        )
        print("✅ Translation catalogs (.po) successfully updated by pybabel.")
    except FileNotFoundError:
        print("❌ Error: Command 'pybabel' not found.", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"❌ Error executing 'pybabel update': {e.stderr}", file=sys.stderr)
        sys.exit(e.returncode)


def compile_cmd() -> None:
    """Compiles .po translation files into binary .mo files for runtime use."""
    command = [
        "pybabel",
        "compile",
        "-d",
        str(LOCALE_DIR),
        "-D",
        LOCALE_DOMAIN,
        "--statistics",
    ]
    print(f"--- Executing: {' '.join(command)}")
    try:
        result = subprocess.run(
            command, check=True, cwd=BASE_DIR, text=True, capture_output=True
        )
        if result.stdout:
            print(result.stdout.strip())
        print("✅ Translation catalogs (.mo) successfully compiled.")
    except FileNotFoundError:
        print("❌ Error: Command 'pybabel' not found.", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"❌ Error executing 'pybabel compile': {e.stderr}", file=sys.stderr)
        if e.stdout:  # Babel compile might print stats to stdout even on error
            print(f"Output from compile: {e.stdout}", file=sys.stderr)
        sys.exit(e.returncode)


def main() -> None:
    """Main function to handle CLI arguments for locale management."""
    if len(sys.argv) < 2:  # noqa: PLR2004 - 2 is standard for checking script name + one argument
        print("Usage: python manage-locales.py [update|compile]")
        sys.exit(1)

    action = sys.argv[1]

    if action == "update":
        update()
    elif action == "compile":
        compile_cmd()
    else:
        print(f"Unknown command: {action}. Valid commands are 'update', 'compile'.")
        sys.exit(1)


if __name__ == "__main__":
    main()
