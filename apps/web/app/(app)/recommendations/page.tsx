"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { unwrap } from "@/lib/api";
import { useAction, useCanEdit, useLatestPlanningRun, useRecommendations, useSuppliers } from "@/lib/hooks";
import { useApi } from "@/lib/org";
import { fmtDate, fmtNum } from "@/lib/utils";
import { PageHeader } from "@/components/shell";
import { ChannelMixBar } from "@/components/channel-mix";
import { ActionBadge, HealthBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Empty } from "@/components/ui/empty";
import { NativeSelect } from "@/components/ui/input";
import { TableSkeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";

export default function RecommendationsPage() {
  const api = useApi();
  const router = useRouter();
  const [supplier, setSupplier] = useState("");
  const [health, setHealth] = useState("");
  const [action, setAction] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const run = useLatestPlanningRun();
  const recs = useRecommendations({ supplier_id: supplier || undefined, health: health || undefined, action: action || undefined });
  const suppliers = useSuppliers();
  const editable = useCanEdit();

  const rows = useMemo(() => (recs.data ?? []).filter((r) => r.action !== "none" || health), [recs.data, health]);
  const orderable = editable ? rows.filter((r) => r.action === "reorder" && !r.po_id && r.supplier_id) : [];
  const chosen = orderable.filter((r) => selected.has(r.id));

  const createPO = useAction(
    async () => unwrap(await api.POST("/purchase-orders/from-recommendations", { body: { recommendation_ids: chosen.map((r) => r.id) } })),
    {
      invalidate: ["recommendations", "purchase-orders"],
      success: (pos) => `${pos.length} draft PO${pos.length === 1 ? "" : "s"} created`,
      onSuccess: (pos) => { setSelected(new Set()); router.push(pos.length === 1 ? `/purchase-orders/${pos[0].id}` : "/purchase-orders"); },
    },
  );

  const toggleAll = () => setSelected(selected.size === orderable.length ? new Set() : new Set(orderable.map((r) => r.id)));

  return (
    <>
      <PageHeader
        title="Recommendations"
        sub={run.data ? `${run.data.n_reorder} reorders · ${run.data.n_produce} production runs · as of ${fmtDate(run.data.as_of)}` : undefined}
        actions={editable ? <Button disabled={!chosen.length} loading={createPO.isPending} onClick={() => createPO.mutate()} data-testid="create-po">Create PO ({chosen.length})</Button> : undefined}
      />
      <div className="mb-3 flex flex-wrap gap-2">
        <NativeSelect value={supplier} onChange={(e) => setSupplier(e.target.value)} className="w-48" data-testid="filter-supplier">
          <option value="">All suppliers</option>
          {suppliers.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </NativeSelect>
        <NativeSelect value={health} onChange={(e) => setHealth(e.target.value)} className="w-40">
          <option value="">All health</option><option value="stockout">Stockout</option><option value="at_risk">At risk</option><option value="healthy">Healthy</option><option value="overstock">Overstock</option>
        </NativeSelect>
        <NativeSelect value={action} onChange={(e) => setAction(e.target.value)} className="w-40">
          <option value="">All actions</option><option value="reorder">Reorder</option><option value="produce">Produce</option>
        </NativeSelect>
      </div>
      {recs.isLoading ? <TableSkeleton /> : rows.length === 0 ? (
        <Empty title="No recommendations" body={run.data ? "Nothing matches these filters." : "Run a forecast and plan first."} action={!run.data ? { label: "Onboarding", href: "/onboarding" } : undefined} />
      ) : (
        <Table>
          <THead>
            <TR>
              <TH>{editable ? <input type="checkbox" aria-label="select all" checked={orderable.length > 0 && selected.size === orderable.length} onChange={toggleAll} data-testid="select-all" /> : null}</TH>
              <TH>SKU</TH><TH className="hidden md:table-cell">Channels</TH><TH>Health</TH><TH>Action</TH><TH className="text-right">Qty</TH><TH>Order by</TH><TH className="hidden md:table-cell">Supplier</TH><TH className="hidden lg:table-cell">Why</TH><TH>PO</TH>
            </TR>
          </THead>
          <TBody>
            {rows.map((r) => {
              const can = r.action === "reorder" && !r.po_id && !!r.supplier_id;
              return (
                <TR key={r.id} data-testid="rec-row">
                  <TD>{editable ? <input type="checkbox" aria-label={`select ${r.sku}`} disabled={!can} checked={selected.has(r.id)} onChange={() => setSelected((s) => { const n = new Set(s); if (n.has(r.id)) n.delete(r.id); else n.add(r.id); return n; })} data-testid="rec-select" /> : null}</TD>
                  <TD><Link href={`/products/${r.product_id}`} className="font-medium hover:underline">{r.sku}</Link></TD>
                  <TD className="hidden md:table-cell"><ChannelMixBar parts={r.channel_mix ?? []} /></TD>
                  <TD><HealthBadge health={r.health} /></TD>
                  <TD><ActionBadge action={r.action} /></TD>
                  <TD className="text-right tabular-nums">{fmtNum(r.qty)}</TD>
                  <TD className="whitespace-nowrap">{fmtDate(r.order_by_date)}</TD>
                  <TD className="hidden md:table-cell">{r.supplier_name ?? <span className="text-xs text-amber-600">none</span>}</TD>
                  <TD className="hidden max-w-md text-xs text-muted-foreground lg:table-cell">{r.reason}</TD>
                  <TD>{r.po_id ? <Link href={`/purchase-orders/${r.po_id}`} className="text-xs underline">view</Link> : null}</TD>
                </TR>
              );
            })}
          </TBody>
        </Table>
      )}
    </>
  );
}
