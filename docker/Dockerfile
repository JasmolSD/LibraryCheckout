FROM python:3.12-slim

# Copy uv from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install OS deps required by reportlab
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6 \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for runtime
RUN useradd -m -u 1000 appuser

# Copy project files (uv.lock ensures reproducible installs)
COPY pyproject.toml uv.lock ./
COPY server ./server
COPY client ./client

# Install runtime dependencies with BuildKit cache mount for fast rebuilds.
# pywebview lives in the desktop group — not needed for the headless API image.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --no-install-project \
    && mkdir -p /app/data /app/logs \
    && chown -R appuser:appuser /app

USER appuser

ENV FLASK_ENV=production \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=5000 \
    LOG_LEVEL=INFO

EXPOSE 5000

# Health check using Python's built-in urllib (no extra deps needed)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/health')" || exit 1

# Headless API mode — uses Flask directly (run.py requires a display for pywebview)
CMD ["uv", "run", "python", "-c", \
     "from server.app import create_app; create_app().run(host='0.0.0.0', port=5000)"]
