#!/bin/sh
# Run migrations (idempotent). Used by the deploy workflow before the new image goes live.
set -e
uv run --no-dev alembic upgrade head
uv run --no-dev alembic current
