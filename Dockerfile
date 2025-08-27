# Этап 1: Сборка и установка зависимостей
FROM python:3.11-slim AS builder

WORKDIR /app

# Устанавливаем uv
RUN pip install uv

# Копируем файлы зависимостей и устанавливаем их
COPY pyproject.toml uv.lock ./
RUN uv sync --all-extras

# Этап 2: Финальный образ
FROM python:3.11-slim

# Устанавливаем системные зависимости, необходимые для распаковки SDK
RUN apt-get update && apt-get install -y p7zip-full && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем установленные зависимости из этапа сборки
COPY --from=builder /app/.venv /app/.venv

# Копируем остальные файлы приложения
COPY . .

# Компилируем файлы локализации, добавив .venv/bin в PATH
RUN PATH="/app/.venv/bin:$PATH" python scripts/manage_locales.py compile

# Указываем команду для запуска приложения
CMD ["/app/.venv/bin/python", "-m", "sender", "--config", "config.toml"]
