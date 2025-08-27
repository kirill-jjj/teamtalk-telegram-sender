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

# --- ИСПРАВЛЕНИЕ ---
# Устанавливаем все системные зависимости: для распаковки (p7zip-full) и для работы SDK (libasound2, libpulse0)
RUN apt-get update && apt-get install -y p7zip-full libasound2 libpulse0 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем установленные зависимости из этапа сборки
COPY --from=builder /app/.venv /app/.venv

# Копируем остальные файлы приложения
COPY . .

# --- ИСПРАВЛЕНИЕ ---
# Патчим библиотеку pytalk, чтобы она не завершала работу после установки SDK
RUN sed -i 's/sys.exit(0)/# sys.exit(0)/' /app/.venv/lib/python3.11/site-packages/pytalk/tools/ttsdk_downloader.py

# Компилируем файлы локализации, добавив .venv/bin в PATH
RUN PATH="/app/.venv/bin:$PATH" python scripts/manage_locales.py compile

# Указываем команду для запуска приложения
CMD ["/app/.venv/bin/python", "-m", "sender", "--config", "config.toml"]
