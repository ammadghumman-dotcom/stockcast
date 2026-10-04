"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

export default function GlobalError({ error }: { error: Error & { digest?: string } }) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);
  return (
    <html lang="en">
      <body className="flex min-h-screen items-center justify-center p-6 text-center">
        <div>
          <h1 className="text-xl font-semibold">Something went wrong</h1>
          <p className="mt-2 text-sm text-muted-foreground">We have been notified. Reload the page or try again in a minute.</p>
          {error.digest ? <p className="mt-4 text-xs text-muted-foreground">ref {error.digest}</p> : null}
        </div>
      </body>
    </html>
  );
}
