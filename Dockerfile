# syntax=docker/dockerfile:1.6
#
# ShopAI production image
#
# Builds a Python 3.12 slim image that can run either the autonomous
# daemon (default) or the HTTP API server (via command arg). Uses a
# multi-stage build to keep the runtime small and a non-root user to
# minimize attack surface.
#
# Build:
#     docker build -t shopai:latest .
#
# Run the daemon (mount data + logs, pull config from .env):
#     docker run --rm \
#         -v $(pwd)/data:/app/data \
#         -v $(pwd)/logs:/app/logs \
#         --env-file .env \
#         shopai:latest
#
# Run the API server (publish port 8080):
#     docker run --rm \
#         -p 8080:8080 \
#         -v $(pwd)/data:/app/data \
#         --env-file .env \
#         shopai:latest api
#
# One-off CLI (e.g. config check, db status):
#     docker run --rm --env-file .env shopai:latest cli config check

# ── Base: system deps + Python ─────────────────────────────────────
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SHOPAI_LOG_FORMAT=json \
    SHOPAI_ENV=production

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        tini \
    && rm -rf /var/lib/apt/lists/*


# ── Dependency layer (cached across code changes) ─────────────────
FROM base AS deps
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt


# ── Runtime ───────────────────────────────────────────────────────
FROM deps AS runtime

# Non-root user for runtime
RUN useradd --create-home --shell /bin/bash --uid 10001 shopai
WORKDIR /app

# Copy the rest of the source. Tests, caches, and git metadata are
# excluded via .dockerignore.
COPY --chown=shopai:shopai . /app

# Persistent directories mounted as volumes in production so SQLite
# files + rotated logs survive container restarts
RUN mkdir -p /app/data /app/logs \
    && chown -R shopai:shopai /app/data /app/logs

USER shopai

ENV PYTHONPATH=/app \
    SHOPAI_DATA_DIR=/app/data \
    SHOPAI_LOG_FILE=/app/logs/shopai.log \
    SHOPAI_LOG_BACKUPS=7

# Lightweight liveness probe — hits the /health endpoint added to
# api.server. Daemon-only containers can disable this with
# `--no-healthcheck`.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8080/health || exit 1

EXPOSE 8080

# tini is PID 1 so SIGTERM propagates cleanly to the Python process
ENTRYPOINT ["/usr/bin/tini", "--", "/app/docker-entrypoint.sh"]
CMD ["daemon"]
