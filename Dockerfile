# Этап 1: Сборка и установка зависимостей
FROM python:3.11-slim AS builder

WORKDIR /app

# Устанавливаем системные зависимости, необходимые для распаковки SDK
RUN apt-get update && apt-get install -y p7zip-full && rm -rf /var/lib/apt/lists/*

# Устанавливаем uv
RUN pip install uv

# Копируем pyproject.toml и устанавливаем зависимости
COPY pyproject.toml ./
RUN uv sync --all-extras

# <-- НОВЫЙ ШАГ: Устанавливаем SDK во время сборки
# Запускаем Python, чтобы импортировать pytalk, что вызовет скачивание и установку SDK.
RUN python -c "import pytalk"

# Этап 2: Финальный образ
FROM python:3.11-slim

# Устанавливаем системные зависимости, которые нужны для работы SDK
RUN apt-get update && apt-get install -y p7zip-full && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем Python-зависимости и uv из этапа сборки
COPY --from=builder /usr/local/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv

# <-- НОВЫЙ ШАГ: Копируем уже установленный SDK из этапа сборки
COPY --from=builder /app/.venv/lib/python3.11/site-packages/pytalk/ttsdk /app/.venv/lib/python3.11/site-packages/pytalk/ttsdk

# Копируем остальные файлы приложения
COPY . .

# Компилируем файлы локализации
RUN uv run i18n compile

# Указываем команду для запуска приложения
CMD ["uv", "run", "sender", "--config", "config.toml"]
