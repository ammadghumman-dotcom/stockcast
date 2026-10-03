FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_SYSTEM_PYTHON=1

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock* requirements-chronos.txt ./
RUN uv sync --frozen --no-dev --no-install-project || uv sync --no-dev --no-install-project
# Chronos-Bolt (CPU-only torch, ~250 MB). Model weights download on first use to HF_HOME.
RUN uv pip install -r requirements-chronos.txt \
      --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple
ENV HF_HOME=/app/.hf-cache

COPY . .

EXPOSE 8000
CMD ["sh", "-c", "uv run --no-dev alembic upgrade head && uv run --no-dev uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"]
