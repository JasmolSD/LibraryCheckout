FROM python:3.12-slim

# Copy uv from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Working dir
WORKDIR /app

# Install OS deps that pywebview / reportlab may need (kept minimal for headless API mode)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6 \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml ./
COPY server ./server
COPY client ./client

# Install dependencies (no dev group, no pywebview needed in headless mode)
RUN uv sync --no-dev --no-install-package pywebview || uv sync --no-dev

# Pre-create runtime dirs
RUN mkdir -p /app/data /app/logs

ENV FLASK_ENV=production \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=5000

EXPOSE 5000

# Headless API mode — uses Flask directly, NOT run.py (which needs a display for pywebview)
CMD ["uv", "run", "python", "-c", "from server.app import create_app; create_app().run(host='0.0.0.0', port=5000)"]