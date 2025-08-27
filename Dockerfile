# Этап 1: Сборка и установка зависимостей
FROM python:3.11-slim AS builder

WORKDIR /app

# Устанавливаем системные зависимости, необходимые для распаковки SDK
RUN apt-get update && apt-get install -y p7zip-full && rm -rf /var/lib/apt/lists/*

# Устанавливаем uv
RUN pip install uv

# Копируем pyproject.toml и устанавливаем зависимости
COPY pyproject.toml uv.lock ./
RUN uv sync --all-extras

# Устанавливаем SDK, запуская Python через uv
RUN uv run python -c "import pytalk"

# Этап 2: Финальный образ
FROM python:3.11-slim

WORKDIR /app

# Копируем ВСЕ виртуальное окружение .venv из билдера
# Это включает Python-библиотеки, скрипты и установленный SDK
COPY --from=builder /app/.venv /app/.venv

# Копируем остальные файлы приложения
COPY . .

# Компилируем файлы локализации, используя Python из нашего .venv
RUN /app/.venv/bin/python scripts/manage_locales.py compile

# Указываем команду для запуска приложения, используя Python из нашего .venv
CMD ["/app/.venv/bin/python", "-m", "sender", "--config", "config.toml"]
