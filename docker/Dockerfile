# ─── Stage 1: Builder ────────────────────────────────────────────────────────
FROM python:3.14-alpine3.23@sha256:f06b9851d8b219335d600ef0ce3c7c091bddeb1916a2e365085ebe0b1da844cd AS builder

# Install uv from the official image (pinned for reproducibility)
COPY --from=ghcr.io/astral-sh/uv:0.12.0@sha256:606e70c71c852d03f611b1e56a195d08648507018a7057fab82c4974c4eae105 /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for layer caching — these change less often than
# source code, so Docker can reuse the cached layer when only code changes.
COPY pyproject.toml uv.lock README.md alembic.ini ./

# Install production dependencies only (no dev extras, no editable installs).
# --frozen ensures uv.lock is not modified during the build.
RUN uv sync --frozen --no-dev --no-editable

# Copy application source and config
COPY src/ src/
COPY scripts/ scripts/
COPY config/ config/
COPY data/ data/

# ─── Stage 2: Runtime ────────────────────────────────────────────────────────
FROM python:3.14-alpine3.23@sha256:f06b9851d8b219335d600ef0ce3c7c091bddeb1916a2e365085ebe0b1da844cd

ARG APP_VERSION=0.1.1
ARG SOURCE_REPOSITORY_URL=https://github.com/Peter-McCann-Strain/Personal_Execution_OS
ARG SOURCE_REVISION=local

LABEL org.opencontainers.image.title="Personal Execution OS backend" \
      org.opencontainers.image.description="API and worker runtime for Personal Execution OS" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.source="${SOURCE_REPOSITORY_URL}" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.licenses="Apache-2.0"

# The core image contains only the Python application. Optional browser/MCP
# runtimes belong in separately versioned sidecars rather than the trusted API
# process.
RUN addgroup -S appuser && \
    adduser -S -D -H -G appuser appuser && \
    mkdir -p /var/lib/personal-execution-os && \
    chown appuser:appuser /var/lib/personal-execution-os

WORKDIR /app

# Copy the entire app (venv + source) from the builder stage
COPY --from=builder --chown=appuser:appuser /app /app

# Put the virtual environment's bin directory on PATH so uvicorn / arq are found
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Switch to non-root user
USER appuser

# Build-time smoke: the runtime UID must be able to write the directory that
# seeds fresh named volumes.
RUN touch /var/lib/personal-execution-os/.write-test && \
    rm /var/lib/personal-execution-os/.write-test

# Default: run the API server.
# Workers override this CMD in docker-compose.yml.
CMD ["uvicorn", "src.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
