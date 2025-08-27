# Этап 1: Сборка и установка зависимостей
FROM python:3.11-slim AS builder

WORKDIR /app

# Устанавливаем системные зависимости, необходимые для распаковки SDK
RUN apt-get update && apt-get install -y p7zip-full && rm -rf /var/lib/apt/lists/*

# Устанавливаем uv
RUN pip install uv

# Копируем pyproject.toml и устанавливаем зависимости в .venv
COPY pyproject.toml ./
RUN uv sync --all-extras

# <-- ИСПРАВЛЕННЫЙ ШАГ: Устанавливаем SDK во время сборки
# Запускаем Python через 'uv run', чтобы он использовал окружение .venv
RUN uv run python -c "import pytalk"

# Этап 2: Финальный образ
FROM python:3.11-slim

# Устанавливаем системные зависимости, которые нужны для работы SDK
RUN apt-get update && apt-get install -y p7zip-full && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# <-- ИСПРАВЛЕННЫЙ ШАГ: Копируем Python-зависимости из .venv в глобальный site-packages
# Это включает pytalk и уже скачанный SDK
COPY --from=builder /app/.venv/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv

# Копируем остальные файлы приложения
COPY . .

# Компилируем файлы локализации
# 'uv run' здесь будет работать, так как 'uv' скопирован, а зависимости в site-packages
RUN uv run i18n compile

# Указываем команду для запуска приложения
CMD ["uv", "run", "sender", "--config", "config.toml"]
