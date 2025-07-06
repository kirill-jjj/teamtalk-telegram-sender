import subprocess
import sys
import os
import argparse
from pathlib import Path

def main():
    """
    Proxy script to run Alembic commands.
    It sets the ALEMBIC_ENV_CONFIG_FILE environment variable based on the
    --config argument, then passes all other arguments to the Alembic CLI.
    """
    parser = argparse.ArgumentParser(
        description="Run Alembic commands with a specific TOML configuration file.",
        usage="migrate [--config CONFIG_FILE.toml] [alembic_command] [alembic_options...]"
    )
    parser.add_argument(
        "--config",
        default="config.toml", # Changed default from .env to config.toml
        help="Path to the TOML configuration file for Alembic's database settings. "
             "This path is relative to the project root. (default: config.toml)"
    )
    # parse_known_args() splits arguments into those recognized by this script's parser
    # and the rest, which are assumed to be for Alembic.
    args, alembic_cli_args = parser.parse_known_args()

    # Determine project root (parent directory of 'scripts/' directory)
    project_root = Path(__file__).resolve().parent.parent

    # Resolve the config file path relative to the project root
    # If args.config is absolute, project_root part is ignored by os.path.join or Path resolution.
    # However, Path resolution with / operator requires the right side to be relative if left is absolute.
    # Safest is to resolve project_root first, then join.
    config_file_on_disk = project_root / args.config
    # Ensure the path is absolute for the environment variable, though not strictly necessary
    # as env.py also resolves it. But good for clarity in logs.
    absolute_config_path = config_file_on_disk.resolve()

    # Set environment variable for alembic/env.py to pick up
    env_vars = os.environ.copy()
    env_vars["ALEMBIC_ENV_CONFIG_FILE"] = str(absolute_config_path)

    print(f"INFO  [run_alembic.py] Setting ALEMBIC_ENV_CONFIG_FILE={absolute_config_path}")

    # Determine Alembic executable.
    # Prefer 'alembic' directly, assuming PATH is correctly set up by `uv run` or similar.
    alembic_executable = "alembic"
    # Fallback for older setups or direct script runs if needed:
    # venv_alembic_path = project_root / ".venv" / "bin" / "alembic"
    # if venv_alembic_path.exists():
    #     alembic_executable = str(venv_alembic_path)
    # else:
    #     print(f"WARN [run_alembic.py] Alembic executable not found at {venv_alembic_path}, relying on PATH.")


    command = [alembic_executable, *alembic_cli_args]

    # For display, convert Path objects in command to string if any were used
    # (though alembic_executable and alembic_cli_args are strings here)
    display_command = [str(c) for c in command]
    print(f"▶️  Executing: {' '.join(display_command)} (CWD: {project_root})")

    try:
        # Run the Alembic command
        subprocess.run(command, check=True, env=env_vars, cwd=project_root)
    except FileNotFoundError:
        print(
            f"Error: '{alembic_executable}' command not found. "
            f"Make sure Alembic is installed and in your PATH, or the virtual environment is active.",
            file=sys.stderr
        )
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        # Alembic usually provides good error messages, so just exit with its return code.
        sys.exit(e.returncode)

if __name__ == "__main__":
    main()
