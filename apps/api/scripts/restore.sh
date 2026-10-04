#!/bin/sh
# Restore a backup into a (fresh or scratch) database. NEVER points at production by accident:
# refuses unless RESTORE_TARGET_URL is set explicitly.
#   scripts/restore.sh s3://bucket/production/stockcast-production-20260101T030000Z.dump
#   scripts/restore.sh /tmp/local.dump
set -eu
SRC="${1:?backup path or s3:// url}"
: "${RESTORE_TARGET_URL:?set RESTORE_TARGET_URL=postgresql://... (a scratch database)}"
ENDPOINT_ARG=""
[ -n "${BACKUP_S3_ENDPOINT:-}" ] && ENDPOINT_ARG="--endpoint-url ${BACKUP_S3_ENDPOINT}"
case "$SRC" in
  s3://*) FILE="/tmp/$(basename "$SRC")"
          # shellcheck disable=SC2086
          python -m scripts.s3 get "$SRC" "$FILE" $ENDPOINT_ARG ;;
  *)      FILE="$SRC" ;;
esac
PG_URL="$(printf '%s' "$RESTORE_TARGET_URL" | sed 's#^postgresql+psycopg://#postgresql://#')"
echo "restore: ${FILE} -> ${PG_URL%%@*}@…"
psql "$PG_URL" -v ON_ERROR_STOP=1 -qc "CREATE EXTENSION IF NOT EXISTS timescaledb;" || true
pg_restore --no-owner --no-privileges --clean --if-exists --dbname "$PG_URL" "$FILE"
echo "restore: verifying"
psql "$PG_URL" -Atc "select count(*) from organizations;" | sed 's/^/organizations: /'
psql "$PG_URL" -Atc "select count(*) from sales_daily;" | sed 's/^/sales_daily rows: /'
DATABASE_URL="$RESTORE_TARGET_URL" alembic current
echo "restore: done"
