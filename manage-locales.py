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
    except tomllib.TOMLDecodeError as tde:
        print(f"⚠️ Warning: Error decoding pyproject.toml: {tde}", file=sys.stderr)
        return "UNKNOWN"
    except IOError as ioe:
        print(f"⚠️ Warning: IOError reading pyproject.toml: {ioe}", file=sys.stderr)
        return "UNKNOWN"
    except Exception as e: # Fallback for other unexpected errors
        print(f"⚠️ Warning: Unexpected error reading version from pyproject.toml: {e}", file=sys.stderr)
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
    print("✅ Translation catalogs (.po) successfully updated by pybabel.")

    print("ℹ️  Post-processing .po files...")
    po_files = list(LOCALE_DIR.glob('*/LC_MESSAGES/*.po'))
    if not po_files:
        print("⚠️ No .po files found for post-processing.")
        return

    for po_file in po_files:
        try:
            print(f"   Processing {po_file.relative_to(BASE_DIR)}...")
            lines = po_file.read_text(encoding='utf-8').splitlines()

            processed_lines = [line for line in lines if not line.startswith('"POT-Creation-Date:')]

            if po_file.name == 'messages.po' and po_file.parent.parent.name == 'en':
                print(f"   Applying special filtering for English file: {po_file.relative_to(BASE_DIR)}")
                header_lines = []
                lang_name_entry_lines = []
                in_header = True
                in_lang_name_entry = False

                # First, extract the header from already POT-Creation-Date-filtered lines
                temp_header_lines = []
                for i, line in enumerate(processed_lines):
                    temp_header_lines.append(line)
                    if line.strip() == 'msgstr ""' and \
                       any(prev_line.strip() == 'msgid ""' for prev_line in processed_lines[max(0,i-5):i]): # Basic header end check
                        # Check if this is the main file header, not a later empty msgid/msgstr
                        is_main_header = True
                        for header_check_idx in range(i + 1, min(i + 10, len(processed_lines))):
                            if processed_lines[header_check_idx].strip().startswith("msgid") and \
                               not processed_lines[header_check_idx].strip().startswith('msgid ""'):
                                is_main_header = False # Found a real msgid, so the previous was part of an entry
                                break
                        if is_main_header:
                            header_lines = temp_header_lines
                            processed_lines = processed_lines[i+1:] # Remaining lines to search for lang_name_entry
                            break

                if not header_lines: # Fallback if precise header detection failed
                    print(f"⚠️  Could not confidently detect header end for {po_file.relative_to(BASE_DIR)}. Keeping all initial non-message lines.")
                    # Take lines until first non-comment, non-empty line that could be a msgid
                    for i, line in enumerate(processed_lines):
                        if line.strip() and not line.startswith("#"):
                             # A bit risky, assuming this is where messages start
                            header_lines = processed_lines[:i]
                            processed_lines = processed_lines[i:]
                            break
                    if not header_lines and processed_lines: # If all are comments or empty
                         header_lines = processed_lines
                         processed_lines = []


                # Now find the language_native_name entry in the rest of the lines
                entry_buffer = []
                for line in processed_lines:
                    if line.startswith('msgid "language_native_name"'):
                        in_lang_name_entry = True
                        lang_name_entry_lines.extend(entry_buffer) # Add preceding comments
                        entry_buffer = []
                        lang_name_entry_lines.append(line)
                    elif in_lang_name_entry:
                        lang_name_entry_lines.append(line)
                        if not line.strip(): # End of entry (empty line)
                            # Check if next line is a new msgid or comment, to confirm end of entry
                            next_line_index = processed_lines.index(line) + 1
                            if next_line_index < len(processed_lines):
                                if processed_lines[next_line_index].startswith("msgid") or \
                                   processed_lines[next_line_index].startswith("#"):
                                    break
                            else: # Reached end of file
                                break
                    elif line.startswith(("#", "msgid")) or not line.strip(): # Part of a potential entry or separator
                         entry_buffer.append(line)
                         if line.startswith("msgid"): # Clear buffer if it was for a different entry
                              entry_buffer = [line]
                    else: # Likely msgstr or continuation, part of an entry
                         entry_buffer.append(line)


                if lang_name_entry_lines:
                    # Ensure there's a blank line between header and entry if both exist
                    final_lines = header_lines
                    if header_lines and lang_name_entry_lines and header_lines[-1].strip() != "":
                        final_lines.append("")
                    final_lines.extend(lang_name_entry_lines)
                    # Ensure a trailing newline if there was content
                    if final_lines and final_lines[-1].strip() != "":
                         final_lines.append("")
                    processed_lines = final_lines
                else:
                    print(f"⚠️  'language_native_name' entry not found in {po_file.relative_to(BASE_DIR)}. English file will only contain header.")
                    processed_lines = header_lines
                    if processed_lines and processed_lines[-1].strip() != "":
                         processed_lines.append("")


            # Write the processed lines back to the file
            # Ensure a final newline if the file is not empty and doesn't end with one
            if processed_lines and processed_lines[-1]:
                po_file.write_text('\n'.join(processed_lines) + '\n', encoding='utf-8')
            elif not processed_lines: # File is empty
                po_file.write_text('', encoding='utf-8')
            else: # File ends with an empty line, but join might miss the final newline
                po_file.write_text('\n'.join(processed_lines), encoding='utf-8')
            print(f"   Finished processing {po_file.relative_to(BASE_DIR)}")

        except IOError as ioe:
            print(f"❌ IOError processing file {po_file.relative_to(BASE_DIR)}: {ioe}", file=sys.stderr)
            # import traceback # Add this import at the top of the file if using traceback
            # traceback.print_exc(file=sys.stderr)
        except Exception as e: # Fallback for truly unexpected errors during string/list manipulation
            print(f"❌ Unexpected error processing file {po_file.relative_to(BASE_DIR)}: {e}", file=sys.stderr)
            # import traceback # Add this import at the top of the file if using traceback
            # traceback.print_exc(file=sys.stderr)

    print("✅ All .po files post-processed.")

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