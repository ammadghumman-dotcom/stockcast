"use client";

import { unwrap } from "@/lib/api";
import { useOrgQuery } from "@/lib/hooks";
import { useApi } from "@/lib/org";

export type ShopifySession = {
  org_id: string;
  org_name: string;
  shop: string;
  channel_id: string;
  installed: boolean;
  plan: string;
  plan_status: string;
  trial_ends_at: string | null;
  is_beta: boolean;
};

/** Bootstraps the embedded app on every open (idempotent): workspace + token-exchange install.
 * Every page calls it first; react-query dedupes it. The API derives the workspace from the
 * session token, so the client never needs the org id. */
export function useShopifySession() {
  const api = useApi();
  return useOrgQuery(["shopify-session"], async () => unwrap(await api.POST("/shopify/session")) as ShopifySession);
}

export function toast(message: string, isError = false) {
  if (typeof window !== "undefined") window.shopify?.toast.show(message, { isError });
}

/** Days left in the trial, or null when not on a trial. */
export function trialDaysLeft(s: Pick<ShopifySession, "plan" | "trial_ends_at">, now = new Date()): number | null {
  if (s.plan !== "trial" || !s.trial_ends_at) return null;
  return Math.max(0, Math.ceil((new Date(s.trial_ends_at).getTime() - now.getTime()) / 86_400_000));
}

export function SessionGate({ children }: { children: (s: ShopifySession) => React.ReactNode }) {
  const s = useShopifySession();
  if (s.isLoading) {
    return (
      <s-page heading="Stockcast">
        <s-section>
          <s-stack direction="inline" gap="base" alignItems="center">
            <s-spinner accessibilityLabel="Loading" />
            <s-text>Connecting to your store…</s-text>
          </s-stack>
        </s-section>
      </s-page>
    );
  }
  if (s.error || !s.data) {
    return (
      <s-page heading="Stockcast">
        <s-banner tone="critical" heading="Stockcast couldn't connect to your store">
          <s-paragraph>{s.error?.message ?? "Reload the page to try again."}</s-paragraph>
        </s-banner>
      </s-page>
    );
  }
  return <>{children(s.data)}</>;
}
