# Operations log

Deploy rollbacks, incidents and restore drills, newest first. (Feature changes live in PRs.)

| Date | Event | Notes |
| --- | --- | --- |
| — | Restore drill | Not yet run — first drill due after the first production deploy. |

## 2026-10-18 — backups were not running
- Found: staging `backup` failed every night since setup (`BACKUP_S3_BUCKET` empty); production
  had no successful backup at all, and the deploy step that ships `backup` ignored failures.
- Fixed: Railway Bucket per environment wired to `backup` by reference variables; staging backup
  verified (`staging/stockcast-staging-20261018T105727Z.dump`, 591 KB). Deploy step now fails if
  `backup` cannot be deployed. `restore.sh` wraps pg_restore in timescaledb_pre/post_restore.
