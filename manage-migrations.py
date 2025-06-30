#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
from pathlib import Path

# Environment variable that bot/config.py will read
CONFIG_FILE_ENV_VAR = "APP_CONFIG_FILE_PATH" # Should match the one in bot/config.py

# Define the root directory of the project where alembic.ini is expected.
# Assumes manage_migrations.py is in the project root.
PROJECT_ROOT = Path(__file__).resolve().parent

def run_alembic_command(config_file_path: str, alembic_args: list[str]):
    """
    Sets the config path environment variable and runs the alembic command.
    """
    # Ensure the config_file_path is absolute, or resolve it relative to project root
    resolved_config_path = Path(config_file_path)
    if not resolved_config_path.is_absolute():
        resolved_config_path = (PROJECT_ROOT / config_file_path).resolve()

    print(f"ℹ️  Using configuration file: {resolved_config_path}")

    # Store original value if exists, to restore later
    original_env_var_value = os.environ.get(CONFIG_FILE_ENV_VAR)
    os.environ[CONFIG_FILE_ENV_VAR] = str(resolved_config_path)

    # Determine path to alembic executable (e.g., from .venv)
    venv_python = Path(sys.executable) # Path to current python interpreter
    alembic_executable = venv_python.parent / "alembic"
    if not alembic_executable.is_file() or not os.access(alembic_executable, os.X_OK):
        # If not found or not executable in venv bin, try just 'alembic' (from PATH)
        alembic_executable = "alembic"

    command = [str(alembic_executable)] + alembic_args

    print(f"▶️  Executing: {' '.join(command)}")
    try:
        # Run from project root so alembic.ini is found and script_location resolves correctly
        # Pass current environment, which includes our new APP_CONFIG_FILE_PATH
        process = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            check=False, # We'll check returncode manually to provide better error messages
            text=True,
            capture_output=True,
            env=os.environ.copy() # Pass a copy of the current environment
        )

        if process.stdout:
            print(process.stdout.strip())
        if process.stderr:
            print(process.stderr.strip(), file=sys.stderr)

        if process.returncode != 0:
            print(f"❌ Error: Alembic command finished with code {process.returncode}.", file=sys.stderr)
            sys.exit(process.returncode)

        print(f"✅ Alembic command '{' '.join(alembic_args)}' executed successfully.")

    except FileNotFoundError:
        print(
            f"❌ Error: Alembic command '{alembic_executable}' not found.",
            "Make sure Alembic is installed and in your PATH or virtual environment.",
            sep="\n", file=sys.stderr
        )
        sys.exit(1)
    # Removed generic CalledProcessError since check=False
    finally:
        # Clean up/restore the environment variable
        if original_env_var_value is None:
            del os.environ[CONFIG_FILE_ENV_VAR]
        else:
            os.environ[CONFIG_FILE_ENV_VAR] = original_env_var_value


def main():
    parser = argparse.ArgumentParser(
        description="Manage Alembic database migrations.",
        epilog="Example: ./manage_migrations.py --config my_prod.env upgrade head"
    )
    parser.add_argument(
        "--config",
        default=".env", # Default config file if not specified
        help="Path to the configuration file (default: .env)"
    )

    subparsers = parser.add_subparsers(dest="alembic_command", required=True, title="Alembic Commands",
                                       help="Run './manage_migrations.py <command> --help' for more on a specific command.")

    common_commands = ["upgrade", "downgrade", "revision", "history", "current", "show", "heads", "branches", "stamp", "edit"]

    for cmd_name in common_commands:
        # For 'edit', it takes a revision and opens an editor, so REMAINDER might be tricky if it expects options.
        # For now, let's assume it's simple.
        cmd_parser = subparsers.add_parser(cmd_name, help=f"Run alembic {cmd_name}. Use -- to pass options to alembic {cmd_name}.")

        if cmd_name == "revision":
            cmd_parser.add_argument("-m", "--message", help="Message for the revision")
            cmd_parser.add_argument("--autogenerate", action="store_true", help="Autogenerate revision from models")

        if cmd_name in ["upgrade", "downgrade", "stamp", "edit"]:
             cmd_parser.add_argument("revision_target", nargs="?", \
                                   help="Revision identifier (e.g., 'head', 'base', specific_rev, +1, -1). For 'edit', this is the revision to edit.")

        # Catch-all for other arguments to pass to alembic for this sub-command
        # Using nargs=argparse.REMAINDER for this.
        # Example: ./manage_migrations.py upgrade head --sql --foo bar
        # 'other_alembic_args' will be ['--sql', '--foo', 'bar']
        cmd_parser.add_argument('other_alembic_args', nargs=argparse.REMAINDER,
                                help="Other arguments to pass directly to the alembic command (e.g. --sql, -x arg).")

    args = parser.parse_args()

    alembic_passthrough_args = [args.alembic_command]

    if args.alembic_command == "revision":
        if args.message:
            alembic_passthrough_args.extend(["-m", args.message])
        if args.autogenerate:
            alembic_passthrough_args.append("--autogenerate")

    if args.alembic_command in ["upgrade", "downgrade", "stamp", "edit"]:
        if hasattr(args, 'revision_target') and args.revision_target:
            alembic_passthrough_args.append(args.revision_target)
        # If revision_target is not provided for upgrade, alembic defaults to 'head'
        # For 'edit', a revision is usually required by alembic itself.

    # Add any other remaining arguments collected by REMAINDER
    # These might be options like --sql, or -x key=value
    if hasattr(args, 'other_alembic_args') and args.other_alembic_args:
        # Remove '--' if present, as it's a common convention for separating args
        cleaned_other_args = [arg for arg in args.other_alembic_args if arg != '--']
        alembic_passthrough_args.extend(cleaned_other_args)

    run_alembic_command(args.config, alembic_passthrough_args)

if __name__ == "__main__":
    main()
