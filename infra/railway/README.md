# Railway config-as-code

One Railway **project** per environment is not needed: use one project `stockcast` with two
Railway **environments**, `staging` and `production` (Settings → Environments). Each
environment has the same five services; variables differ per environment.

| Service   | Config file                 | Source                                  |
| --------- | --------------------------- | --------------------------------------- |
| `api`     | `infra/railway/api.json`    | this repo, root `/`                     |
| `worker`  | `infra/railway/worker.json` | this repo, root `/`                     |
| `beat`    | `infra/railway/beat.json`   | this repo, root `/` (exactly 1 replica) |
| `backup`  | `infra/railway/backup.json` | this repo, root `/` (cron 03:00 UTC)    |
| `postgres`| Railway template **TimescaleDB** (`timescale/timescaledb:latest-pg16`) with a volume |
| `redis`   | Railway template Redis      |                                         |

For each code service: Settings → Build → *Config-as-code file path* = the file above, and turn
**off** "Auto deploy on push" — deploys are driven by `.github/workflows/deploy.yml` (`railway up`)
so that migrations, smoke tests and the production approval gate run in order.

Variables (reference the managed services with `${{Postgres.DATABASE_URL}}` etc.):

```
ENV=staging|production            DATABASE_URL=${{Postgres.DATABASE_URL}}   # add +psycopg (see below)
CELERY_BROKER_URL=${{Redis.REDIS_URL}}/1   RATE_LIMIT_STORAGE=${{Redis.REDIS_URL}}/2
AUTH_MODE=clerk  CLERK_JWKS_URL  CLERK_ISSUER  CLERK_SECRET_KEY
CREDENTIALS_KEY  FORCE_HTTPS=true  CORS_ORIGINS=https://app.stockcast.app  ALLOWED_HOSTS=api.stockcast.app
APP_BASE_URL=https://api.stockcast.app  WEB_BASE_URL=https://app.stockcast.app
STRIPE_*  RESEND_API_KEY  SHOPIFY_*  AMAZON_*  EBAY_*  AMAZON_WEBHOOK_SECRET
SENTRY_DSN  OTEL_EXPORTER_OTLP_ENDPOINT  OTEL_EXPORTER_OTLP_HEADERS  ALERT_WEBHOOK_URL
LOG_FORMAT=json  RELEASE (set by the deploy workflow)
BACKUP_S3_BUCKET  BACKUP_S3_ENDPOINT  AWS_ACCESS_KEY_ID  AWS_SECRET_ACCESS_KEY  BACKUP_PREFIX
CELERY_CONCURRENCY=2 (worker)  WEB_CONCURRENCY=2 (api)
```

`DATABASE_URL` must use the `postgresql+psycopg://` scheme: set it to
`postgresql+psycopg://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/${{Postgres.PGDATABASE}}`.
