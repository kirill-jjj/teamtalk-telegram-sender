#!/usr/bin/env python3
"""
Utility for managing project localization files using Babel.

The script provides a command-line interface for performing
the following actions:
- extract: extract translatable strings from source code into a .pot file.
- update: update .po files for each language based on the .pot template.
- compile: compile .po files into binary .mo files.

For help, use the 'help' command. When run without arguments,
all three actions are performed sequentially.
"""

import sys
import subprocess
import tomllib
from pathlib import Path
from typing import List

# --- Configuration: explicit definition of constants ---
PROJECT_NAME = "teamtalk-telegram-sender"
COPYRIGHT_HOLDER = "kirill-jjj"
LOCALE_DOMAIN = "messages"
BABEL_CONFIG = "babel.cfg"

# --- Paths: using pathlib for reliability ---
try:
    BASE_DIR = Path(__file__).resolve().parent
    LOCALE_DIR = BASE_DIR / "locales"
    POT_FILE = LOCALE_DIR / f"{LOCALE_DOMAIN}.pot"
except NameError:
    BASE_DIR = Path.cwd()
    LOCALE_DIR = BASE_DIR / "locales"
    POT_FILE = LOCALE_DIR / f"{LOCALE_DOMAIN}.pot"

def run_command(command: List[str]) -> None:
    """
    Executes an external command and handles errors. (DRY principle)

    Args:
        command: The command and its arguments as a list.
    """
    print(f"▶️  Executing: {' '.join(command)}")
    try:
        # Explicit and safe subprocess call
        result = subprocess.run(
            command,
            check=True,  # Will raise an exception on error
            text=True,
            capture_output=True,
            encoding='utf-8',
            cwd=BASE_DIR
        )
        # Print stdout if it exists (useful for compile --statistics)
        if result.stdout:
            print(result.stdout.strip())

    except FileNotFoundError:
        # Error handling if Babel is not installed or not in PATH
        print(
            f"❌ Error: Command '{command[0]}' not found.",
            "Make sure Babel is installed (`pip install Babel`)",
            "and that the path to 'pybabel' is in the PATH environment variable.",
            sep="\n", file=sys.stderr
        )
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        # Detailed error output for easy debugging
        print(
            f"❌ Error: Command finished with code {e.returncode}.",
            "--- stderr output: ---",
            e.stderr.strip(),
            "-----------------------",
            sep="\n", file=sys.stderr
        )
        sys.exit(1)

def get_project_version() -> str:
    """Reads the project version from pyproject.toml."""
    try:
        pyproject_path = BASE_DIR / "pyproject.toml"
        with open(pyproject_path, "rb") as f: # tomllib expects bytes
            data = tomllib.load(f)
        # Assuming version is under [project][version] based on typical structure
        version = data.get("project", {}).get("version")
        if version:
            return str(version)
        # Fallback or error if not found, adjust as needed
        print("⚠️ Warning: Version not found in pyproject.toml under project.version.", file=sys.stderr)
        return "UNKNOWN"
    except FileNotFoundError:
        print("⚠️ Warning: pyproject.toml not found. Cannot determine project version.", file=sys.stderr)
        return "UNKNOWN"
    except Exception as e:
        print(f"⚠️ Warning: Error reading version from pyproject.toml: {e}", file=sys.stderr)
        return "UNKNOWN"

def extract_messages() -> None:
    """Extracts translatable strings into a .pot file."""
    project_version = get_project_version()
    command = [
        "uv", "run", "pybabel", "extract",
        "-F", BABEL_CONFIG,
        "-o", str(POT_FILE),
        f"--project={PROJECT_NAME}",
        f"--version={project_version}",
        f"--copyright-holder={COPYRIGHT_HOLDER}",
        "."
    ]
    run_command(command)
    print(f"✅ Messages successfully extracted to '{POT_FILE.relative_to(BASE_DIR)}'")

def update_catalogs() -> None:
    """Updates .po files based on the .pot template."""
    command = [
        "uv", "run", "pybabel", "update",
        "-i", str(POT_FILE),
        "-d", str(LOCALE_DIR),
        "-D", LOCALE_DOMAIN,
        # "--update-header-comment", # Removed to prevent PO-Revision-Date changes
        "--previous"
    ]
    run_command(command)
    print("✅ Translation catalogs (.po) successfully updated.")

def compile_catalogs() -> None:
    """Compiles .po files into binary .mo files."""
    command = [
        "uv", "run", "pybabel", "compile",
        "-d", str(LOCALE_DIR),
        "-D", LOCALE_DOMAIN,
        "--statistics"
    ]
    run_command(command)
    print("✅ Translation catalogs (.mo) successfully compiled.")

def print_help() -> None:
    """Prints help information on how to use the script."""
    # Use the module's docstring as the source of help (DRY principle)
    print(sys.modules[__name__].__doc__)
    print("Available commands:")
    print("  extract      - Only extract strings to .pot file.")
    print("  update       - Only update .po files.")
    print("  compile      - Only compile .mo files.")
    print("  help         - Show this help message.")
    print("\nWithout arguments - extract, update, compile are performed sequentially.")

def main() -> None:
    """Main function, controls logic based on arguments."""
    actions = {
        "extract": extract_messages,
        "update": update_catalogs,
        "compile": compile_catalogs,
        "help": print_help,
    }

    action_key = sys.argv[1] if len(sys.argv) > 1 else "all"

    if action_key == "all":
        print("--- Starting full localization update cycle ---\n")
        extract_messages()
        update_catalogs()
        compile_catalogs()
        print("\n🎉 All localization steps completed successfully.")
    elif action_key in actions:
        actions[action_key]()
    else:
        print(f"❌ Unknown command: '{action_key}'", file=sys.stderr)
        print("Use the 'help' command for assistance.", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()