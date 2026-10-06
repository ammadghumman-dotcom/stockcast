"use client";

import { useEffect } from "react";

/** PostHog pageviews for the public site and app. Loads nothing unless the key is set;
 * product events (connect, first forecast viewed, first PO) are captured server-side. */
export function Analytics() {
  useEffect(() => {
    const key = process.env.NEXT_PUBLIC_POSTHOG_KEY;
    if (!key) return;
    let cancelled = false;
    void import("posthog-js").then(({ default: posthog }) => {
      if (cancelled) return;
      posthog.init(key, {
        api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST ?? "https://us.i.posthog.com",
        capture_pageview: "history_change",
        person_profiles: "identified_only",
        mask_all_text: true,
        disable_session_recording: true,
      });
    });
    return () => {
      cancelled = true;
    };
  }, []);
  return null;
}
