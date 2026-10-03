import { withSentryConfig } from "@sentry/nextjs/config";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  transpilePackages: ["@stockcast/shared"],
};

// Source maps upload only when a Sentry auth token is present (the deploy workflow); otherwise
// this is a no-op wrapper and the build stays identical to plain Next.
export default withSentryConfig(nextConfig, {
  silent: true,
  org: process.env.SENTRY_ORG,
  project: process.env.SENTRY_PROJECT,
  authToken: process.env.SENTRY_AUTH_TOKEN,
  sourcemaps: { disable: !process.env.SENTRY_AUTH_TOKEN },
  telemetry: false,
});
