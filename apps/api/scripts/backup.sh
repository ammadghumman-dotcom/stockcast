#!/bin/sh
# Daily logical backup of Postgres to S3-compatible storage (Cloudflare R2 / Backblaze B2 / S3)
# with BACKUP_RETENTION_DAYS retention. Runs as the Railway cron service `backup`
# (infra/railway/backup.json, 03:00 UTC). Railway's own volume snapshots are a second copy.
#
# Env: DATABASE_URL, BACKUP_S3_BUCKET, BACKUP_S3_ENDPOINT (optional), AWS_ACCESS_KEY_ID,
#      AWS_SECRET_ACCESS_KEY, BACKUP_RETENTION_DAYS (30), BACKUP_PREFIX (env name)
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
uv run --no-dev python -m scripts.s3 put "$FILE" "s3://${BACKUP_S3_BUCKET}/${PREFIX}/$(basename "$FILE")" $ENDPOINT_ARG
# shellcheck disable=SC2086
uv run --no-dev python -m scripts.s3 prune "s3://${BACKUP_S3_BUCKET}/${PREFIX}/" --days "$RETENTION" $ENDPOINT_ARG
rm -f "$FILE"
echo "backup: done"
