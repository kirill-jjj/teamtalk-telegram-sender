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

# Устанавливаем SDK
RUN uv run python -c "import pytalk"

# Этап 2: Финальный образ
FROM python:3.11-slim

# Устанавливаем системные зависимости, которые нужны для работы SDK
RUN apt-get update && apt-get install -y p7zip-full && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем uv из билдера
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv

# Копируем файлы проекта
COPY . .

# Устанавливаем зависимости ЗАНОВО, используя кэш Docker.
# Это создает чистое и рабочее .venv в финальном образе.
RUN uv sync --all-extras

# Компилируем локализацию
RUN uv run i18n compile

# Указываем команду для запуска приложения
CMD ["uv", "run", "sender", "--config", "config.toml"]
