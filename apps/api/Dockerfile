# Production image for api / worker / beat (same image, different start command).
# Build: docker build -t stockcast-api apps/api
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_SYSTEM_PYTHON=1 UV_COMPILE_BYTECODE=1 \
    HF_HOME=/app/.hf-cache PORT=8000

RUN apt-get update && apt-get install -y --no-install-recommends curl postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv \
    && useradd -r -u 1000 app

WORKDIR /app
COPY pyproject.toml uv.lock* requirements-chronos.txt ./
RUN uv sync --frozen --no-dev --no-install-project || uv sync --no-dev --no-install-project
# Chronos-Bolt (CPU-only torch, ~250 MB) into the project venv. Weights download to HF_HOME.
RUN uv pip install --python .venv/bin/python -r requirements-chronos.txt \
      --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple \
    && find /app/.venv -name "*.pyc" -delete

# No recursive chown (it would duplicate the venv layer); only the cache dir needs writes.
COPY --chown=app:app . .
RUN chmod +x scripts/*.sh && mkdir -p /app/.hf-cache && chown app:app /app/.hf-cache
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD curl -fsS "http://localhost:${PORT}/health" || exit 1

# ---- dev (docker compose): auto-reload, migrations on start
FROM base AS dev
USER root
CMD ["sh", "-c", "uv run --no-dev alembic upgrade head && uv run --no-dev uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"]

# ---- prod (Railway): migrations run by the deploy workflow / preDeploy, not here
FROM base AS prod
CMD ["sh", "-c", "uv run --no-dev uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY:-2} --proxy-headers --forwarded-allow-ips='*' --no-access-log"]
