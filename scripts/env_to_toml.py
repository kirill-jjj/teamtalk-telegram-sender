"""Converts .env configuration files to a structured TOML format."""

import argparse
from collections.abc import Callable
from pathlib import Path
import sys
from typing import Any

from dotenv import dotenv_values  # For reading .env files
import toml  # For writing TOML


def parse_comma_separated_string_to_list(v: Any) -> list[str]:  # noqa: ANN401
    """Parses a comma-separated string into a list of stripped strings.

    Returns an empty list if the input is not a string or is an empty/whitespace string.
    """
    if isinstance(v, str) and v.strip():
        return [s.strip() for s in v.split(",")]
    return []


ConversionRule = Callable[[Any], Any] | type  # UP007
EnvMappingType = dict[str, tuple[str, str, ConversionRule]]

# Define the mapping from .env keys to TOML structure
# Format: env_key: (toml_section, toml_key, type_conversion_function_or_literal)
ENV_TO_TOML_MAPPING: EnvMappingType = {
    "TELEGRAM_BOT_EVENT_TOKEN": ("telegram", "event_token", str),
    "TG_BOT_MESSAGE_TOKEN": ("telegram", "message_token", str),
    "TG_ADMIN_CHAT_ID": ("telegram", "admin_chat_id", int),
    "HOST_NAME": ("teamtalk", "host_name", str),
    "PORT": ("teamtalk", "port", int),
    "ENCRYPTED": (
        "teamtalk",
        "encrypted",
        lambda v: v.lower() == "true" if isinstance(v, str) else bool(v),
    ),
    "USER_NAME": ("teamtalk", "user_name", str),
    "PASSWORD": ("teamtalk", "password", str),
    "CHANNEL": ("teamtalk", "channel", str),
    "CHANNEL_PASSWORD": (
        "teamtalk",
        "channel_password",
        str,
    ),  # Will be empty string if missing/empty in .env
    "NICK_NAME": ("teamtalk", "nick_name", str),
    "STATUS_TEXT": ("teamtalk", "status_text", str),
    "CLIENT_NAME": ("teamtalk", "client_name", str),
    "SERVER_NAME": (
        "teamtalk",
        "server_name",
        str,
    ),  # Will be empty string if missing/empty in .env
    "ADMIN_USERNAME": (
        "general",
        "admin_username",
        str,
    ),  # Will be empty string if missing/empty in .env
    "GLOBAL_IGNORE_USERNAMES": (
        "teamtalk",
        "global_ignore_usernames",
        parse_comma_separated_string_to_list,
    ),
    "DATABASE_FILE": ("database", "db_file", str),
    "DEFAULT_LANG": ("general", "default_lang", str),
    "GENDER": ("general", "gender", str),
    "DEEPLINK_TTL_SECONDS": ("operational_parameters", "deeplink_ttl_seconds", int),
    "TT_RECONNECT_RETRY_SECONDS": (
        "operational_parameters",
        "tt_reconnect_retry_seconds",
        int,
    ),
    "TT_RECONNECT_CHECK_INTERVAL_SECONDS": (
        "operational_parameters",
        "tt_reconnect_check_interval_seconds",
        int,
    ),
    "ONLINE_USERS_CACHE_SYNC_INTERVAL_SECONDS": (
        "operational_parameters",
        "online_users_cache_sync_interval_seconds",
        int,
    ),
}

DEFAULT_EXCLUDE_DIRS = [
    ".venv",
    ".git",
    "__pycache__",
    "alembic",
    "node_modules",
    "dist",
    "build",
    "scripts",
]


def convert_value(raw_value: Any, conversion_rule: ConversionRule, env_key: str) -> Any:  # noqa: ANN401
    """Applies the specified conversion rule to the raw value from .env."""
    # dotenv_values typically returns None if the key exists but has no value
    # (e.g. KEY=)
    # or if the key is not in the file at all when iterating its result.
    # However, we iterate items from dotenv_values, so raw_value is what's after '='.
    # An empty value (KEY=) results in raw_value being an empty string.

    is_optional_empty_string_field = env_key in [
        "CHANNEL_PASSWORD",
        "SERVER_NAME",
        "ADMIN_USERNAME",
    ]
    is_optional_empty_list_field = env_key == "GLOBAL_IGNORE_USERNAMES"

    if (
        raw_value == "" or raw_value is None
    ):  # Treat None from direct access or empty string from .env as "empty"
        if is_optional_empty_string_field:
            return ""
        if is_optional_empty_list_field:
            return []
        # For other types, if the .env value is empty, it's problematic for int/bool.
        # Let Pydantic handle defaults for these if they are not in TOML.
        # So, if value is empty and not one of above, we skip it (return None).
        # This print is acceptable for a CLI script's direct feedback.
        print(
            f"Info: Empty value for '{env_key}' in .env, will be omitted from TOML. "
            f"Pydantic defaults may apply.",
            file=sys.stderr,
        )
        return None

    try:
        # conversion_rule is always a callable (a function like `int`, `str`, `bool`,
        # or a custom lambda/function) as per ENV_TO_TOML_MAPPING definition.
        return conversion_rule(raw_value)
    except ValueError as e:
        # Attempt to get a meaningful name for the conversion rule for the
        # warning message.
        # For built-in types like int, str, bool, __name__ gives the type name.
        # For functions (including lambdas), __name__ gives the function name.
        conversion_name = getattr(conversion_rule, "__name__", str(conversion_rule))
        print(
            f"Warning: Could not convert value '{raw_value}' for key '{env_key}' "
            f"using {conversion_name}. Error: {e}. Storing as raw string.",
            file=sys.stderr,
        )
        return str(raw_value)  # Fallback to string if conversion fails


def process_single_env_file(input_env_path: Path, output_toml_path: Path) -> bool:
    """Converts a single .env file to a .toml file.

    Args:
        input_env_path: Path to the input .env file.
        output_toml_path: Path for the output .toml file.

    Returns:
        True on successful conversion, False otherwise.
    """
    if not input_env_path.is_file():
        print(f"Error: Input file not found: {input_env_path}", file=sys.stderr)
        return False

    print(f"Processing '{input_env_path}' -> '{output_toml_path}'...")
    env_vars = dotenv_values(input_env_path)
    toml_data: dict[str, dict[str, Any]] = {}

    for env_key_orig, env_value in env_vars.items():
        env_key = str(env_key_orig).strip()
        if not env_key:
            continue  # Skip empty keys that might result from comment lines etc.

        if env_key in ENV_TO_TOML_MAPPING:
            section, toml_key, conversion_func = ENV_TO_TOML_MAPPING[env_key]
            converted_value = convert_value(env_value, conversion_func, env_key)

            if (
                converted_value is not None
            ):  # Add to TOML only if there's a meaningful converted value
                if section not in toml_data:
                    toml_data[section] = {}
                toml_data[section][toml_key] = converted_value
        else:
            print(
                f"Warning: Unmapped key '{env_key}' from '{input_env_path}' "
                f"will be ignored.",
                file=sys.stderr,
            )

    try:
        output_toml_path.parent.mkdir(parents=True, exist_ok=True)
        with output_toml_path.open("w", encoding="utf-8") as f:
            toml.dump(toml_data, f)
        print(f"Successfully converted to '{output_toml_path}'.")
    except OSError as e:
        print(f"Error writing TOML file '{output_toml_path}': {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(
            f"Error during TOML generation for '{output_toml_path}': {e}",
            file=sys.stderr,
        )
        return False
    else:
        return True


def _process_all_env_files(project_root: Path, exclude_dirs_str: str) -> None:
    """Scans and converts all found .env files in the project directory."""
    print(
        f"Searching for .env files in '{project_root}' and subdirectories "
        f"(excluding: {exclude_dirs_str})..."
    )
    excluded_dir_parts = {
        Path(d.strip()).name for d in exclude_dirs_str.split(",") if d.strip()
    }

    env_files_to_process = []
    for p in project_root.rglob("*"):
        if p.is_file() and (p.name.endswith(".env") or ".env." in p.name):
            if not any(
                part in excluded_dir_parts for part in p.relative_to(project_root).parts
            ):
                env_files_to_process.append(p)
            else:
                print(f"Skipping excluded file by directory: {p}", file=sys.stderr)

    if not env_files_to_process:
        print("No .env files found to convert (after exclusions).")
        sys.exit(0)

    print(f"Found {len(env_files_to_process)} '.env' files to process:")
    for f_path in env_files_to_process:
        print(f"  - {f_path}")

    converted_count = 0
    found_files_count = len(env_files_to_process)

    for env_file_path_item in env_files_to_process:
        output_toml_path_item = (
            (project_root / "config.toml")
            if env_file_path_item.name == ".env"
            and env_file_path_item.parent == project_root
            else env_file_path_item.with_suffix(".toml")
        )
        if process_single_env_file(env_file_path_item, output_toml_path_item):
            converted_count += 1

    print(f"\nProcessed {found_files_count} '.env' files found.")
    print(f"Successfully converted {converted_count} files.")
    if converted_count < found_files_count:
        sys.exit(1)


def _process_specific_env_file(config_path: Path, output_path_arg: Path | None) -> None:
    """Processes a single specified .env file."""
    input_file_path = config_path.resolve()
    if output_path_arg:
        output_file_path = output_path_arg.resolve()
    elif input_file_path.name == ".env":
        output_file_path = input_file_path.parent / "config.toml"
    else:
        output_file_path = input_file_path.with_suffix(".toml")

    if not process_single_env_file(input_file_path, output_file_path):
        sys.exit(1)


def main() -> None:
    """Main function to handle CLI args and orchestrate .env to .toml conversion."""
    parser = argparse.ArgumentParser(
        description="Convert .env file(s) to structured TOML format.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--config",
        type=Path,
        metavar="<path_to_env_file>",
        help="Path to a specific input .env file to convert.",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help=(
            "Convert all *.env files found in the project root and subdirectories "
            "(respects --exclude-dirs)."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        metavar="<path_to_toml_file>",
        help=(
            "Path for the output .toml file (only applicable if --config is "
            "specified).\nDefaults to the input filename with .toml extension in "
            "the same directory, or 'config.toml' if input is '.env'."
        ),
    )
    parser.add_argument(
        "--exclude-dirs",
        type=str,
        default=",".join(DEFAULT_EXCLUDE_DIRS),
        help=(
            f"Comma-separated list of directory names to exclude when using --all.\n"
            f"Default: {','.join(DEFAULT_EXCLUDE_DIRS)}"
        ),
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help=(
            "Project root directory for --all scan. Default: current working "
            "directory."
        ),
    )

    args = parser.parse_args()

    if args.config:
        _process_specific_env_file(args.config, args.output)
    elif args.all:
        _process_all_env_files(args.project_root.resolve(), args.exclude_dirs)


if __name__ == "__main__":
    main()
