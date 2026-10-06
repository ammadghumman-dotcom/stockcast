"use client";

import { unwrap } from "@/lib/api";
import { useAction, useRecommendations } from "@/lib/hooks";
import { useApi } from "@/lib/org";
import { fmtDate, fmtNum } from "@/lib/utils";
import { SessionGate, toast } from "@/components/shopify/session";

const HEALTH_TONE: Record<string, string> = {
  stockout: "critical",
  at_risk: "warning",
  overstock: "info",
  healthy: "success",
};
const HEALTH_LABEL: Record<string, string> = {
  stockout: "Out of stock",
  at_risk: "At risk",
  overstock: "Overstock",
  healthy: "Healthy",
};

export default function ShopifyRecommendations() {
  return <SessionGate>{() => <Plan />}</SessionGate>;
}

function Plan() {
  const api = useApi();
  const recs = useRecommendations();
  const actions = (recs.data ?? []).filter((r) => r.action !== "none");
  const orderable = actions.filter((r) => r.action === "reorder" && r.supplier_id && !r.po_id);
  const createPOs = useAction(
    async () =>
      unwrap(
        await api.POST("/purchase-orders/from-recommendations", {
          body: { recommendation_ids: orderable.map((r) => r.id) },
        }),
      ),
    {
      invalidate: ["recommendations", "purchase-orders"],
      onSuccess: (pos) =>
        toast(`Created ${pos.length} draft purchase order${pos.length === 1 ? "" : "s"}`),
    },
  );

  return (
    <s-page heading="Reorder plan">
      {orderable.length ? (
        <s-button
          slot="primary-action"
          variant="primary"
          loading={createPOs.isPending || undefined}
          onClick={() => createPOs.mutate(undefined)}
        >
          Create draft purchase orders ({orderable.length})
        </s-button>
      ) : null}
      {recs.isLoading ? (
        <s-section>
          <s-spinner accessibilityLabel="Loading plan" />
        </s-section>
      ) : actions.length === 0 ? (
        <s-section heading="Nothing to order right now">
          <s-paragraph>
            Every product has enough stock for its lead time and safety buffer. Stockcast checks
            again every night after new orders come in.
          </s-paragraph>
        </s-section>
      ) : (
        <s-section padding="none">
          <s-table>
            <s-table-header-row>
              <s-table-header listSlot="primary">Product</s-table-header>
              <s-table-header>Status</s-table-header>
              <s-table-header>Action</s-table-header>
              <s-table-header format="numeric">Quantity</s-table-header>
              <s-table-header>Order by</s-table-header>
              <s-table-header>Runs out</s-table-header>
            </s-table-header-row>
            <s-table-body>
              {actions.map((r) => (
                <s-table-row key={r.id}>
                  <s-table-cell>
                    <s-stack gap="small-500">
                      <s-text type="strong">{r.product_name}</s-text>
                      <s-text color="subdued">{r.reason}</s-text>
                    </s-stack>
                  </s-table-cell>
                  <s-table-cell>
                    <s-badge tone={HEALTH_TONE[r.health] ?? "neutral"}>
                      {HEALTH_LABEL[r.health] ?? r.health}
                    </s-badge>
                  </s-table-cell>
                  <s-table-cell>{r.action === "produce" ? "Produce" : "Reorder"}</s-table-cell>
                  <s-table-cell>{fmtNum(Number(r.qty))}</s-table-cell>
                  <s-table-cell>{fmtDate(r.order_by_date)}</s-table-cell>
                  <s-table-cell>{r.stockout_date ? fmtDate(r.stockout_date) : "Not in horizon"}</s-table-cell>
                </s-table-row>
              ))}
            </s-table-body>
          </s-table>
        </s-section>
      )}
    </s-page>
  );
}
