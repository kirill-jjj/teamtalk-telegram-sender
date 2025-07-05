import subprocess
import sys
import os

def main():
    """Простой прокси-скрипт для запуска alembic с кастомным конфигом."""

    # Ищем аргумент --config
    config_file = ".env" # Значение по умолчанию
    cli_args = sys.argv[1:]

    # Ensure the script can find bot.config by adding project root to sys.path
    # This assumes scripts/run_alembic.py is one level down from project root.
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    try:
        # Простой поиск и извлечение --config
        config_index = cli_args.index("--config")
        if config_index + 1 < len(cli_args):
            config_file = cli_args[config_index + 1]
            # Удаляем --config и его значение из списка аргументов для alembic
            del cli_args[config_index:config_index + 2]
        else:
            # Handle case where --config is the last argument without a value
            print("Error: --config option requires a value.", file=sys.stderr)
            sys.exit(1)
    except ValueError:
        # Если --config не найден, используется значение по умолчанию
        pass
    except IndexError:
        # Should not happen if ValueError is caught first for missing --config
        # but as a safeguard if cli_args[config_index + 1] fails for other reasons.
        print("Error: Malformed --config option.", file=sys.stderr)
        sys.exit(1)

    # Формируем команду для alembic
    # Ensure alembic is found, might need to be 'python -m alembic' if not in PATH
    # For now, assume 'alembic' is directly callable.
    # We will pass the config file path via an environment variable
    # as -x attributes are not reliably being passed through.
    env_vars = os.environ.copy()
    env_vars["ALEMBIC_ENV_CONFIG_FILE"] = config_file

    print(f"INFO  [run_alembic.py] Setting ALEMBIC_ENV_CONFIG_FILE={config_file}")

    # Remove -x argument, it's not working
    command = [
        "alembic",
        *cli_args    # Передаем все остальные аргументы (e.g., upgrade head)
    ]

    print(f"▶️  Executing: {' '.join(command)}")
    # Запускаем команду
    try:
        subprocess.run(command, check=True, env=env_vars)
    except FileNotFoundError:
        print(f"Error: 'alembic' command not found. Make sure Alembic is installed and in your PATH.", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        # Alembic command itself exited with an error
        # No need to print full stack trace, alembic usually gives good errors
        sys.exit(e.returncode)

if __name__ == "__main__":
    main()
