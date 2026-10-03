import * as Sentry from "@sentry/nextjs";

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.NEXT_PUBLIC_ENV ?? process.env.NODE_ENV,
    release: process.env.NEXT_PUBLIC_RELEASE,
    tracesSampleRate: 0.1,
  });
}
