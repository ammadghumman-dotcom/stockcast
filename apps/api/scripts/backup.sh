#!/bin/sh
# Daily logical backup of Postgres to S3-compatible storage (Cloudflare R2 / Backblaze B2 / S3)
# with BACKUP_RETENTION_DAYS retention. Runs as the Railway cron service `backup`
# (infra/railway/backup.json, 03:00 UTC). Railway's own volume snapshots are a second copy.
#
# Env: DATABASE_URL, BACKUP_S3_BUCKET, BACKUP_S3_ENDPOINT (optional), AWS_ACCESS_KEY_ID,
#      AWS_SECRET_ACCESS_KEY, BACKUP_RETENTION_DAYS (30), BACKUP_PREFIX (env name),
#      RESTORE_DRILL=1 (staging only): after uploading, restore the dump into a scratch database
#      on the same server, compare row counts with the source, drop it; any mismatch fails the run.
set -eu
: "${DATABASE_URL:?}" "${BACKUP_S3_BUCKET:?}"
PREFIX="${BACKUP_PREFIX:-${ENV:-dev}}"
RETENTION="${BACKUP_RETENTION_DAYS:-30}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="/tmp/stockcast-${PREFIX}-${STAMP}.dump"
ENDPOINT_ARG=""
[ -n "${BACKUP_S3_ENDPOINT:-}" ] && ENDPOINT_ARG="--endpoint-url ${BACKUP_S3_ENDPOINT}"

# SQLAlchemy URL -> libpq URL
PG_URL="$(printf '%s' "$DATABASE_URL" | sed 's#^postgresql+psycopg://#postgresql://#')"

echo "backup: dumping to ${FILE}"
pg_dump --format=custom --compress=6 --no-owner --no-privileges "$PG_URL" > "$FILE"
SIZE="$(wc -c < "$FILE")"
echo "backup: ${SIZE} bytes"
[ "$SIZE" -gt 10000 ] || { echo "backup: dump suspiciously small"; exit 1; }

# shellcheck disable=SC2086
python -m scripts.s3 put "$FILE" "s3://${BACKUP_S3_BUCKET}/${PREFIX}/$(basename "$FILE")" $ENDPOINT_ARG
if [ "${RESTORE_DRILL:-0}" = "1" ]; then
  DRILL_DB="stockcast_restore_drill"
  QUERY=""
  case "$PG_URL" in *\?*) QUERY="?${PG_URL#*\?}" ;; esac
  NOQ="${PG_URL%%\?*}"
  DRILL_URL="${NOQ%/*}/${DRILL_DB}${QUERY}"
  echo "restore drill: restoring into ${DRILL_DB}"
  psql "$PG_URL" -v ON_ERROR_STOP=1 -qc "DROP DATABASE IF EXISTS ${DRILL_DB}"
  psql "$PG_URL" -v ON_ERROR_STOP=1 -qc "CREATE DATABASE ${DRILL_DB}"
  RESTORE_TARGET_URL="$DRILL_URL" sh scripts/restore.sh "$FILE"
  for t in organizations products sales_daily; do
    SRC_N="$(psql "$PG_URL" -Atc "select count(*) from ${t}")"
    DST_N="$(psql "$DRILL_URL" -Atc "select count(*) from ${t}")"
    echo "restore drill: ${t} source=${SRC_N} restored=${DST_N}"
    # the source may gain rows after the dump, never lose them
    [ "$DST_N" -gt 0 ] && [ "$DST_N" -le "$SRC_N" ] || { echo "restore drill: FAILED on ${t}"; exit 1; }
  done
  psql "$PG_URL" -qc "DROP DATABASE IF EXISTS ${DRILL_DB}"
  echo "restore drill: ok"
fi

# shellcheck disable=SC2086
python -m scripts.s3 prune "s3://${BACKUP_S3_BUCKET}/${PREFIX}/" --days "$RETENTION" $ENDPOINT_ARG
rm -f "$FILE"
echo "backup: done"
