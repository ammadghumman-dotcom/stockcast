"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import type { Product, Recommendation } from "@stockcast/shared";

import { fmtDate, fmtNum } from "@/lib/utils";
import { ActionBadge, HealthBadge } from "@/components/ui/badge";
import { Empty } from "@/components/ui/empty";
import { Input, NativeSelect } from "@/components/ui/input";
import { TableSkeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";

export function ProductsTable({
  products,
  recs,
  loading,
  emptyTitle,
}: {
  products: Product[] | undefined;
  recs: Recommendation[] | undefined;
  loading: boolean;
  emptyTitle: string;
}) {
  const [q, setQ] = useState("");
  const [health, setHealth] = useState("");
  const byProduct = useMemo(() => new Map((recs ?? []).map((r) => [r.product_id, r])), [recs]);
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (products ?? [])
      .filter((p) => !needle || p.sku.toLowerCase().includes(needle) || p.name.toLowerCase().includes(needle))
      .map((p) => ({ p, r: byProduct.get(p.id) }))
      .filter(({ r }) => !health || r?.health === health)
      .sort((a, b) => (a.r?.days_of_cover ?? 1e9) - (b.r?.days_of_cover ?? 1e9));
  }, [products, byProduct, q, health]);

  if (loading) return <TableSkeleton />;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Input placeholder="Search SKU or name" value={q} onChange={(e) => setQ(e.target.value)} className="max-w-xs" data-testid="search" />
        <NativeSelect value={health} onChange={(e) => setHealth(e.target.value)} className="w-40">
          <option value="">All health</option>
          <option value="stockout">Stockout</option>
          <option value="at_risk">At risk</option>
          <option value="healthy">Healthy</option>
          <option value="overstock">Overstock</option>
        </NativeSelect>
        <span className="self-center text-xs text-muted-foreground">{rows.length} of {products?.length ?? 0}</span>
      </div>
      {rows.length === 0 ? <Empty title={emptyTitle} /> : (
        <Table>
          <THead>
            <TR><TH>SKU</TH><TH className="hidden md:table-cell">Name</TH><TH>Health</TH><TH className="text-right">On hand</TH><TH className="text-right">Cover (d)</TH><TH>Next action</TH><TH className="hidden lg:table-cell">Stockout</TH></TR>
          </THead>
          <TBody>
            {rows.map(({ p, r }) => (
              <TR key={p.id} data-testid="product-row">
                <TD><Link href={`/products/${p.id}`} className="font-medium hover:underline">{p.sku}</Link><div className="text-xs text-muted-foreground md:hidden">{p.name}</div></TD>
                <TD className="hidden md:table-cell">{p.name}</TD>
                <TD><HealthBadge health={r?.health} /></TD>
                <TD className="text-right tabular-nums">{fmtNum(r?.on_hand)}</TD>
                <TD className="text-right tabular-nums">{r?.days_of_cover ?? (r ? "90+" : "–")}</TD>
                <TD><ActionBadge action={r?.action} />{r && r.action !== "none" ? <span className="ml-2 text-xs text-muted-foreground">{fmtNum(r.qty)} by {fmtDate(r.order_by_date)}</span> : null}</TD>
                <TD className="hidden lg:table-cell">{fmtDate(r?.stockout_date)}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
    </div>
  );
}
