#!/usr/bin/env python3
import subprocess
import sys
import tomllib
from pathlib import Path

# Constants
PROJECT_NAME = "teamtalk-telegram-sender"
COPYRIGHT_HOLDER = "kirill-jjj"
BABEL_CONFIG = "babel.cfg" # Assumed to be in BASE_DIR
LOCALE_DOMAIN = "messages" # Domain for .mo files

try:
    BASE_DIR = Path(__file__).resolve().parent
    LOCALE_DIR = BASE_DIR / "locales"
    POT_FILE = LOCALE_DIR / f"{LOCALE_DOMAIN}.pot"
except NameError: # Fallback for __file__ not defined
    BASE_DIR = Path.cwd()
    LOCALE_DIR = BASE_DIR / "locales"
    POT_FILE = LOCALE_DIR / f"{LOCALE_DOMAIN}.pot"

def get_project_version() -> str:
    """Reads the version from pyproject.toml."""
    pyproject_path = BASE_DIR / "pyproject.toml"
    try:
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        # Assuming version is under [project][version]
        version = data.get("project", {}).get("version")
        if version:
            return str(version)
        print("⚠️ Warning: Version not found in pyproject.toml under project.version.", file=sys.stderr)
        return "0.0.0" # Fallback version
    except FileNotFoundError:
        print(f"⚠️ Warning: pyproject.toml not found at {pyproject_path}. Cannot determine project version.", file=sys.stderr)
        return "0.0.0" # Fallback version
    except (tomllib.TOMLDecodeError, KeyError, AttributeError, TypeError) as e: # Broader catch for TOML issues or structure changes
        print(f"⚠️ Warning: Could not read version from pyproject.toml: {e}", file=sys.stderr)
        return "0.0.0" # Fallback version

def extract():
    """Extracts translatable strings into a .pot file."""
    version = get_project_version()
    command = [
        "pybabel", "extract",
        "-F", str(BASE_DIR / BABEL_CONFIG), # Ensure full path to babel.cfg
        "-o", str(POT_FILE),
        f"--project={PROJECT_NAME}",
        f"--version={version}",
        f"--copyright-holder={COPYRIGHT_HOLDER}",
        # Assuming source files are scanned from BASE_DIR
        ".", # Source path to scan
    ]
    print(f"▶️  Executing: {' '.join(command)}")
    try:
        subprocess.run(command, check=True, cwd=BASE_DIR, text=True, capture_output=True)
        print(f"✅ Messages extracted to '{POT_FILE.relative_to(BASE_DIR)}'")
    except FileNotFoundError:
        print(f"❌ Error: Command 'pybabel' not found. Make sure Babel is installed and in your PATH.", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"❌ Error executing 'pybabel extract': {e.stderr}", file=sys.stderr)
        sys.exit(e.returncode)


def update():
    """Updates .po files based on the .pot template."""
    command = [
        "pybabel", "update",
        "-i", str(POT_FILE),
        "-d", str(LOCALE_DIR), # Directory containing language folders
        "-D", LOCALE_DOMAIN,   # Domain (usually 'messages')
        "--previous" # Use .po~ backup files
    ]
    print(f"▶️  Executing: {' '.join(command)}")
    try:
        subprocess.run(command, check=True, cwd=BASE_DIR, text=True, capture_output=True)
        print(f"✅ Translation catalogs (.po) successfully updated by pybabel.")
    except FileNotFoundError:
        print(f"❌ Error: Command 'pybabel' not found.", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"❌ Error executing 'pybabel update': {e.stderr}", file=sys.stderr)
        sys.exit(e.returncode)

def compile_cmd():
    """Compiles .po files into binary .mo files."""
    command = [
        "pybabel", "compile",
        "-d", str(LOCALE_DIR), # Directory containing language folders
        "-D", LOCALE_DOMAIN,   # Domain
        "--statistics"
    ]
    print(f"▶️  Executing: {' '.join(command)}")
    try:
        result = subprocess.run(command, check=True, cwd=BASE_DIR, text=True, capture_output=True)
        if result.stdout:
            print(result.stdout.strip())
        print(f"✅ Translation catalogs (.mo) successfully compiled.")
    except FileNotFoundError:
        print(f"❌ Error: Command 'pybabel' not found.", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"❌ Error executing 'pybabel compile': {e.stderr}", file=sys.stderr)
        if e.stdout: # Babel compile might print stats to stdout even on error
            print(f"Output from compile: {e.stdout}", file=sys.stderr)
        sys.exit(e.returncode)

def main():
    if len(sys.argv) < 2:
        print("Usage: python manage-locales.py [extract|update|compile]")
        sys.exit(1)

    action = sys.argv[1]

    if action == "extract":
        extract()
    elif action == "update":
        update()
    elif action == "compile":
        compile_cmd()
    else:
        print(f"Unknown command: {action}. Valid commands are 'extract', 'update', 'compile'.")
        sys.exit(1)

if __name__ == "__main__":
    main()