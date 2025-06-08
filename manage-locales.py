#!/usr/bin/env python3
"""
Утилита для управления файлами локализации проекта с использованием Babel.

Скрипт предоставляет интерфейс командной строки для выполнения
следующих действий:
- extract: извлечение переводимых строк из исходного кода в .pot-файл.
- update: обновление .po-файлов для каждого языка на основе .pot-шаблона.
- compile: компиляция .po-файлов в бинарные .mo-файлы.

Для справки используйте команду 'help'. При запуске без аргументов
выполняются все три действия последовательно.
"""

import sys
import subprocess
from pathlib import Path
from typing import List

# --- Конфигурация: явное определение констант ---
PROJECT_NAME = "teamtalk-telegram-sender"
COPYRIGHT_HOLDER = "kirill-jjj"
LOCALE_DOMAIN = "messages"
BABEL_CONFIG = "babel.cfg"

# --- Пути: использование pathlib для надежности ---
try:
    BASE_DIR = Path(__file__).resolve().parent
    LOCALE_DIR = BASE_DIR / "bot" / "locales"
    POT_FILE = LOCALE_DIR / f"{LOCALE_DOMAIN}.pot"
except NameError:
    BASE_DIR = Path.cwd()
    LOCALE_DIR = BASE_DIR / "bot" / "locales"
    POT_FILE = LOCALE_DIR / f"{LOCALE_DOMAIN}.pot"

def run_command(command: List[str]) -> None:
    """
    Выполняет внешнюю команду и обрабатывает ошибки. (Принцип DRY)

    Args:
        command: Команда и ее аргументы в виде списка.
    """
    print(f"▶️  Выполнение: {' '.join(command)}")
    try:
        # Явный и безопасный вызов подпроцесса
        result = subprocess.run(
            command,
            check=True,  # Вызовет исключение при ошибке
            text=True,
            capture_output=True,
            encoding='utf-8',
            cwd=BASE_DIR
        )
        # Выводим stdout, если он есть (полезно для compile --statistics)
        if result.stdout:
            print(result.stdout.strip())

    except FileNotFoundError:
        # Обработка ошибки, если Babel не установлен или не в PATH
        print(
            f"❌ Ошибка: Команда '{command[0]}' не найдена.",
            "Убедитесь, что Babel установлен (`pip install Babel`)",
            "и что путь к 'pybabel' находится в переменной окружения PATH.",
            sep="\n", file=sys.stderr
        )
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        # Детальный вывод ошибки для легкой отладки
        print(
            f"❌ Ошибка: Команда завершилась с кодом {e.returncode}.",
            "--- Вывод stderr: ---",
            e.stderr.strip(),
            "-----------------------",
            sep="\n", file=sys.stderr
        )
        sys.exit(1)

def extract_messages() -> None:
    """Извлекает переводимые строки в .pot-файл."""
    command = [
        "pybabel", "extract",
        "-F", BABEL_CONFIG,
        "-o", str(POT_FILE),
        f"--project={PROJECT_NAME}",
        f"--copyright-holder={COPYRIGHT_HOLDER}",
        "--keywords=_",
        "."
    ]
    run_command(command)
    print(f"✅ Сообщения успешно извлечены в '{POT_FILE.relative_to(BASE_DIR)}'")

def update_catalogs() -> None:
    """Обновляет .po-файлы на основе .pot-шаблона."""
    command = [
        "pybabel", "update",
        "-i", str(POT_FILE),
        "-d", str(LOCALE_DIR),
        "-D", LOCALE_DOMAIN,
        "--update-header-comment",
        "--previous"
    ]
    run_command(command)
    print("✅ Каталоги переводов (.po) успешно обновлены.")

def compile_catalogs() -> None:
    """Компилирует .po-файлы в бинарные .mo-файлы."""
    command = [
        "pybabel", "compile",
        "-d", str(LOCALE_DIR),
        "-D", LOCALE_DOMAIN,
        "--statistics"
    ]
    run_command(command)
    print("✅ Каталоги переводов (.mo) успешно скомпилированы.")

def print_help() -> None:
    """Выводит справочную информацию по использованию скрипта."""
    # Используем docstring модуля как источник справки (принцип DRY)
    print(sys.modules[__name__].__doc__)
    print("Доступные команды:")
    print("  extract      - Только извлечение строк в .pot-файл.")
    print("  update       - Только обновление .po-файлов.")
    print("  compile      - Только компиляция .mo-файлов.")
    print("  help         - Показать это справочное сообщение.")
    print("\nБез аргументов - последовательно выполняются extract, update, compile.")

def main() -> None:
    """Главная функция, управляющая логикой на основе аргументов."""
    actions = {
        "extract": extract_messages,
        "update": update_catalogs,
        "compile": compile_catalogs,
        "help": print_help,
    }

    action_key = sys.argv[1] if len(sys.argv) > 1 else "all"

    if action_key == "all":
        print("--- Запуск полного цикла обновления локализации ---\n")
        extract_messages()
        update_catalogs()
        compile_catalogs()
        print("\n🎉 Все шаги локализации успешно завершены.")
    elif action_key in actions:
        actions[action_key]()
    else:
        print(f"❌ Неизвестная команда: '{action_key}'", file=sys.stderr)
        print("Используйте команду 'help' для справки.", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()