import subprocess
import sys
import os

def main():
    """Simple proxy script to run alembic with a custom config."""

    config_file = ".env"
    cli_args = sys.argv[1:]

    # Ensure the script can find bot.config by adding project root to sys.path
    # This assumes scripts/run_alembic.py is one level down from project root.
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    try:
        config_index = cli_args.index("--config")
        if config_index + 1 < len(cli_args):
            config_file = cli_args[config_index + 1]
            del cli_args[config_index:config_index + 2]
        else:
            print("Error: --config option requires a value.", file=sys.stderr)
            sys.exit(1)
    except ValueError:
        pass
    except IndexError:
        # Should not happen if ValueError is caught first for missing --config
        # but as a safeguard if cli_args[config_index + 1] fails for other reasons.
        print("Error: Malformed --config option.", file=sys.stderr)
        sys.exit(1)

    # Ensure alembic is found, might need to be 'python -m alembic' if not in PATH
    # For now, assume 'alembic' is directly callable.
    # We will pass the config file path via an environment variable
    # as -x attributes are not reliably being passed through.
    env_vars = os.environ.copy()
    env_vars["ALEMBIC_ENV_CONFIG_FILE"] = config_file

    print(f"INFO  [run_alembic.py] Setting ALEMBIC_ENV_CONFIG_FILE={config_file}")

    command = [
        "alembic",
        *cli_args
    ]

    print(f"▶️  Executing: {' '.join(command)}")
    try:
        subprocess.run(command, check=True, env=env_vars)
    except FileNotFoundError:
        print(f"Error: 'alembic' command not found. Make sure Alembic is installed and in your PATH.", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        # No need to print full stack trace, alembic usually gives good errors
        sys.exit(e.returncode)

if __name__ == "__main__":
    main()
