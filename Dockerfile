FROM python:3.11-slim AS builder
WORKDIR /app

# Install uv for dependency sync.
RUN pip install --no-cache-dir uv

# Install dependencies into the project venv.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Final image.
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# Runtime system packages.
RUN apt-get update \
    && apt-get install -y --no-install-recommends p7zip-full libasound2 libpulse0 \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user.
RUN useradd --create-home --uid 10001 appuser

WORKDIR /app

# Copy the virtualenv and app sources.
COPY --from=builder /app/.venv /app/.venv
COPY --chown=appuser:appuser . .

# Compile locales with the venv python.
RUN python scripts/manage_locales.py compile

USER appuser

CMD ["python", "-m", "sender", "--config", "config.toml"]
