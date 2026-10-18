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
# TimescaleDB: hypertables and continuous aggregates restore correctly only between
# timescaledb_pre_restore() and timescaledb_post_restore() (this is also why pg_dump warns about
# "circular foreign-key constraints ... continuous_agg"). Skipped on plain Postgres.
TSDB="$(psql "$PG_URL" -Atc "select count(*) from pg_extension where extname='timescaledb'")"
[ "$TSDB" = "1" ] && psql "$PG_URL" -v ON_ERROR_STOP=1 -qc "SELECT timescaledb_pre_restore();"
pg_restore --no-owner --no-privileges --clean --if-exists --dbname "$PG_URL" "$FILE"
[ "$TSDB" = "1" ] && psql "$PG_URL" -v ON_ERROR_STOP=1 -qc "SELECT timescaledb_post_restore();"
echo "restore: verifying"
psql "$PG_URL" -Atc "select count(*) from organizations;" | sed 's/^/organizations: /'
psql "$PG_URL" -Atc "select count(*) from sales_daily;" | sed 's/^/sales_daily rows: /'
DATABASE_URL="$RESTORE_TARGET_URL" alembic current
echo "restore: done"
