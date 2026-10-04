# Railway setup

One Railway **project** with two Railway **environments**, `staging` and `production`
(Settings → Environments → New Environment → *Duplicate* production). Each environment has the
same six services; variables differ per environment.

> Railway deprecated *Config as Code* on 2026-08-28 (services created after that date cannot opt
> in), so the `*.json` files in this folder are **reference only** — the settings below are made in
> the Railway UI per service. The deploy workflow (`railway up --service …`) does not depend on them.

| Service       | Source                                   | Settings (Railway UI)                                                                                        |
| ------------- | ---------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `api`         | this repo, **Root Directory `apps/api`** | Builder **Dockerfile** (path `Dockerfile`), pre-deploy `sh scripts/migrate.sh`, healthcheck `/health/ready`, public domain on port 8000 |
| `worker`      | this repo, root `apps/api`               | Builder Dockerfile, start `sh scripts/start-worker.sh`                                                        |
| `beat`        | this repo, root `apps/api`               | Builder Dockerfile, start `sh scripts/start-beat.sh`, exactly 1 replica                                       |
| `backup`      | this repo, root `apps/api`               | Builder Dockerfile, start `sh scripts/backup.sh`, cron schedule `0 3 * * *`                                   |
| `timescaledb` | Docker image `timescale/timescaledb:latest-pg16` | volume at `/var/lib/postgresql/data`, `PGDATA=/var/lib/postgresql/data/pgdata`                         |
| `Redis`       | Railway Database → Redis                 |                                                                                                              |

The root directory must be `apps/api` because the Dockerfile copies `pyproject.toml` from its own
directory (the same context `docker compose` uses). For every code service **disconnect the branch
trigger** (Source → Branch → Disconnect) — deploys are driven by `.github/workflows/deploy.yml`
(`railway up`) so that migrations, smoke tests and the production gate run in order.

Variables. The `api` service holds the canonical set; `worker`, `beat` and `backup` reference it
(`${{api.VAR}}`) so secrets are entered once per environment:

```
# timescaledb service
POSTGRES_USER=stockcast  POSTGRES_DB=stockcast  POSTGRES_PASSWORD=${{secret(32)}}
PGDATA=/var/lib/postgresql/data/pgdata
DATABASE_URL=postgresql+psycopg://${{POSTGRES_USER}}:${{POSTGRES_PASSWORD}}@${{RAILWAY_PRIVATE_DOMAIN}}:5432/${{POSTGRES_DB}}

# api service
ENV=staging|production  AUTH_MODE=clerk  LOG_FORMAT=json  FORCE_HTTPS=true  WEB_CONCURRENCY=2
DATABASE_URL=${{timescaledb.DATABASE_URL}}
CELERY_BROKER_URL=${{Redis.REDIS_URL}}/1   RATE_LIMIT_STORAGE=${{Redis.REDIS_URL}}/2
APP_BASE_URL=https://${{RAILWAY_PUBLIC_DOMAIN}}  ALLOWED_HOSTS=${{RAILWAY_PUBLIC_DOMAIN}}
WEB_BASE_URL=https://<vercel host>  CORS_ORIGINS=https://<vercel host>
CREDENTIALS_KEY (Fernet)  CLERK_JWKS_URL  CLERK_ISSUER  CLERK_SECRET_KEY
STRIPE_SECRET_KEY  STRIPE_WEBHOOK_SECRET  STRIPE_PRICE_STARTER|GROWTH|SCALE  RESEND_API_KEY
SHOPIFY_*  AMAZON_*  EBAY_*  AMAZON_WEBHOOK_SECRET
SENTRY_DSN  OTEL_EXPORTER_OTLP_ENDPOINT  OTEL_EXPORTER_OTLP_HEADERS  ALERT_WEBHOOK_URL
RELEASE (set by the deploy workflow)

# worker: everything above as ${{api.VAR}} + CELERY_CONCURRENCY=2
# beat:   everything above as ${{api.VAR}}
# backup: ENV, DATABASE_URL as ${{api.VAR}} + BACKUP_PREFIX=<env> BACKUP_RETENTION_DAYS=30
#         BACKUP_S3_BUCKET BACKUP_S3_ENDPOINT AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION
```

The api refuses to boot (`security.production_guard`) until a non-default `CREDENTIALS_KEY`,
`AUTH_MODE=clerk`, `FORCE_HTTPS=true` and https `CORS_ORIGINS` are set — expect the healthcheck to
fail on the first deploy of a fresh environment until the secrets are in.

Billing is optional. Leave every `STRIPE_*` variable empty to run without a payment provider
(Stripe doesn't onboard Pakistan-based accounts): trials never lock, the plan page shows
"Early access" and checkout is hidden. Setting `STRIPE_SECRET_KEY` turns billing on, and then
`STRIPE_WEBHOOK_SECRET` becomes mandatory.
