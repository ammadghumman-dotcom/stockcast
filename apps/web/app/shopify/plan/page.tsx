"use client";

import { unwrap } from "@/lib/api";
import { useAction, useOrgQuery } from "@/lib/hooks";
import { useApi } from "@/lib/org";
import { SessionGate, toast } from "@/components/shopify/session";
import { limitText } from "@/lib/shopify-embed";

type BillingPlan = {
  key: string;
  name: string;
  price_usd: number;
  beta_price_usd: number;
  channels: number | null;
  skus: number | null;
};
type Billing = {
  plans: BillingPlan[];
  current_plan: string;
  plan_status: string;
  effective_plan: string;
  is_beta: boolean;
  beta_discount_months: number;
};

export default function ShopifyPlan() {
  return <SessionGate>{() => <Plans />}</SessionGate>;
}

function Plans() {
  const api = useApi();
  const billing = useOrgQuery(["shopify-billing"], async () => unwrap(await api.GET("/shopify/billing")) as Billing);
  const subscribe = useAction(
    async (plan: string) =>
      unwrap(await api.POST("/shopify/billing/subscribe", { body: { plan } })) as { confirmation_url: string },
    {
      onSuccess: (r) => {
        // Charge approval lives in the Shopify admin, outside our iframe
        window.open(r.confirmation_url, "_top");
      },
    },
  );
  if (subscribe.error) toast(subscribe.error.message, true);
  const b = billing.data;
  return (
    <s-page heading="Plan and billing">
      {!b ? (
        <s-section>
          <s-spinner accessibilityLabel="Loading plans" />
        </s-section>
      ) : (
        <>
          <s-section>
            <s-paragraph>
              {b.current_plan === "trial"
                ? "You're on the free trial with Growth limits."
                : `You're on the ${b.plans.find((p) => p.key === b.current_plan)?.name ?? b.current_plan} plan (${b.plan_status}).`}{" "}
              Charges appear on your Shopify invoice.
              {b.is_beta
                ? ` As a beta brand you get 50% off for your first ${b.beta_discount_months} months.`
                : ""}
            </s-paragraph>
          </s-section>
          <s-grid gridTemplateColumns="repeat(auto-fit, minmax(220px, 1fr))" gap="base">
            {b.plans.map((p) => {
              const current = p.key === b.current_plan && b.plan_status === "active";
              return (
                <s-section key={p.key} heading={p.name}>
                  <s-stack gap="small">
                    <s-text type="strong">
                      ${b.is_beta ? p.beta_price_usd : p.price_usd}/month
                      {b.is_beta ? ` for ${b.beta_discount_months} months, then $${p.price_usd}` : ""}
                    </s-text>
                    <s-text>{limitText(p.channels, "sales channel")}</s-text>
                    <s-text>{limitText(p.skus, "SKU")}</s-text>
                    {current ? (
                      <s-badge tone="success">Current plan</s-badge>
                    ) : (
                      <s-button
                        variant={p.key === "growth" ? "primary" : "secondary"}
                        loading={(subscribe.isPending && subscribe.variables === p.key) || undefined}
                        onClick={() => subscribe.mutate(p.key)}
                      >
                        Choose {p.name}
                      </s-button>
                    )}
                  </s-stack>
                </s-section>
              );
            })}
          </s-grid>
        </>
      )}
    </s-page>
  );
}
