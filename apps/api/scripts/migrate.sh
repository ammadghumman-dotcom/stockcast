#!/bin/sh
# Run migrations (idempotent). Used by the deploy workflow before the new image goes live.
set -e
alembic upgrade head
alembic current
