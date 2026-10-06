"use client";

import { useEffect } from "react";

import { unwrap } from "@/lib/api";
import { useOrgQuery } from "@/lib/hooks";
import { useApi } from "@/lib/org";
import { useOnboarding } from "@/components/onboarding-checklist";
import { SessionGate, trialDaysLeft, type ShopifySession } from "@/components/shopify/session";

/** Steps a merchant can finish inside the Shopify admin link to embedded pages; the rest open
 * the full Stockcast app (bills of materials and suppliers have richer editors there). */
const EMBEDDED_HREF: Record<string, string> = {
  connect: "/shopify",
  forecast: "/shopify/recommendations",
  po: "/shopify/recommendations",
};

export default function ShopifyHome() {
  return <SessionGate>{(s) => <Home session={s} />}</SessionGate>;
}

function Home({ session }: { session: ShopifySession }) {
  const api = useApi();
  const runs = useOrgQuery(["sync-runs", session.channel_id], async () =>
    unwrap(
      await api.GET("/channels/{channel_id}/sync-runs", {
        params: { path: { channel_id: session.channel_id }, query: { limit: 1 } },
      }),
    ),
  );
  const onboarding = useOnboarding();
  const last = runs.data?.[0];
  const syncing = !last || last.status === "running" || last.status === "queued";
  useEffect(() => {
    if (!syncing) return;
    const t = setInterval(() => runs.refetch(), 4000);
    return () => clearInterval(t);
  }, [syncing, runs]);
  const days = trialDaysLeft(session);

  return (
    <s-page heading="Stockcast">
      <s-button slot="primary-action" variant="primary" href="/shopify/recommendations">
        View reorder plan
      </s-button>

      {days !== null ? (
        <s-banner tone={days <= 3 ? "warning" : "info"} heading={`${days} days left in your free trial`}>
          <s-paragraph>
            Choose a plan any time; the remaining trial days carry over.{" "}
            <s-link href="/shopify/plan">See plans</s-link>
          </s-paragraph>
        </s-banner>
      ) : null}

      <s-section heading="Your store">
        <s-stack gap="small">
          <s-text>{session.shop}</s-text>
          {last?.status === "failed" ? (
            <s-banner tone="critical" heading="The last import failed">
              <s-paragraph>{last.error ?? "We'll retry tonight."}</s-paragraph>
            </s-banner>
          ) : syncing ? (
            <s-stack direction="inline" gap="small" alignItems="center">
              <s-spinner accessibilityLabel="Importing" size="base" />
              <s-text>
                Importing up to two years of orders and current stock. Forecasts appear when this
                finishes, usually within a few minutes.
              </s-text>
            </s-stack>
          ) : (
            <s-paragraph>
              Imported {last.rows_products ?? 0} products and {last.rows_sales ?? 0} sales records.
              Orders and stock levels now update automatically.
            </s-paragraph>
          )}
        </s-stack>
      </s-section>

      {onboarding.data && !onboarding.data.complete ? (
        <s-section heading={`Get set up (${onboarding.data.done} of ${onboarding.data.total})`}>
          <s-ordered-list>
            {onboarding.data.steps.map((step) => (
              <s-list-item key={step.key}>
                <s-stack direction="inline" gap="small" alignItems="center">
                  {step.done ? (
                    <s-badge tone="success">Done</s-badge>
                  ) : (
                    <s-badge>To do</s-badge>
                  )}
                  {step.done ? (
                    <s-text>{step.title}</s-text>
                  ) : (
                    <s-link
                      href={EMBEDDED_HREF[step.key] ?? `${process.env.NEXT_PUBLIC_SITE_URL ?? ""}${step.href}`}
                      target={EMBEDDED_HREF[step.key] ? undefined : "_blank"}
                    >
                      {step.title}
                    </s-link>
                  )}
                </s-stack>
              </s-list-item>
            ))}
          </s-ordered-list>
        </s-section>
      ) : null}

      <s-section heading="How Stockcast plans your stock">
        <s-paragraph>
          Every night Stockcast forecasts each product from your sales history, adjusts for holidays
          and promotions, and works out what to reorder or produce, and by when, so you don&apos;t
          run out. If you make your own products, add a bill of materials and Stockcast plans the
          raw materials too.
        </s-paragraph>
      </s-section>
    </s-page>
  );
}
