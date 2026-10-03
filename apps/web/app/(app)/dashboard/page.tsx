"use client";

import Link from "next/link";

import { unwrap } from "@/lib/api";
import { useAction, useLatestPlanningRun, useOrgQuery, useRecommendations } from "@/lib/hooks";
import { useApi } from "@/lib/org";
import { daysFromToday, fmtDate, fmtMoney, fmtNum } from "@/lib/utils";
import { PageHeader } from "@/components/shell";
import { ActionBadge, HealthBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tile } from "@/components/ui/card";
import { Empty } from "@/components/ui/empty";
import { TableSkeleton, TilesSkeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";

export default function Dashboard() {
  const api = useApi();
  const run = useLatestPlanningRun();
  const recs = useRecommendations();
  const accuracy = useOrgQuery(["forecast-accuracy"], async () => unwrap(await api.GET("/forecast-accuracy")));
  const rerun = useAction(
    async () => {
      unwrap(await api.POST("/forecast-runs", { params: { query: { horizon: 90 } } }));
      return unwrap(await api.POST("/planning-runs"));
    },
    { success: "Forecast and plan refreshed", invalidate: [] },
  );

  const list = recs.data ?? [];
  const hc = run.data?.health_counts ?? {};
  const cash = run.data?.cash_by_health ?? {};
  const stockouts30 = list.filter((r) => { const d = daysFromToday(r.stockout_date); return d !== null && d <= 30; }).length;
  const actions = list.filter((r) => r.action !== "none").slice(0, 20);

  return (
    <>
      <PageHeader
        title="Dashboard"
        sub={run.data?.as_of ? `Plan as of ${fmtDate(run.data.as_of)}` : undefined}
        actions={<Button onClick={() => rerun.mutate()} loading={rerun.isPending} variant="outline" data-testid="rerun">Re-run forecast & plan</Button>}
      />
      {run.isLoading ? <TilesSkeleton /> : !run.data ? (
        <Empty title="No plan yet" body="Import data or connect a store, then run your first forecast." action={{ label: "Go to onboarding", href: "/onboarding" }} />
      ) : (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Tile label="SKUs at risk" value={fmtNum((hc.at_risk ?? 0) + (hc.stockout ?? 0))} sub={`${hc.stockout ?? 0} already out`} tone={(hc.at_risk ?? 0) + (hc.stockout ?? 0) > 0 ? "warn" : "ok"} testId="tile-at-risk" />
          <Tile label="Stockouts next 30 days" value={fmtNum(stockouts30)} tone={stockouts30 > 0 ? "bad" : "ok"} testId="tile-stockouts" />
          <Tile label="Overstock cash" value={fmtMoney(cash.overstock ?? 0)} sub={`${hc.overstock ?? 0} SKUs`} tone="info" testId="tile-overstock" />
          <Tile label="Forecast accuracy" value={accuracy.data?.wape != null ? `${(100 * (1 - Number(accuracy.data.wape))).toFixed(0)}%` : "–"} sub={accuracy.data?.wape != null ? `WAPE ${Number(accuracy.data.wape).toFixed(2)} on ${accuracy.data.skus} SKUs` : "no backtest yet"} testId="tile-accuracy" />
        </div>
      )}

      <h2 className="mb-2 mt-6 text-lg font-semibold">Top actions</h2>
      {recs.isLoading ? <TableSkeleton /> : actions.length === 0 ? (
        <Empty title="Nothing to do" body="No reorders or production runs are needed within the planning horizon." />
      ) : (
        <Table>
          <THead>
            <TR><TH>SKU</TH><TH>Health</TH><TH>Action</TH><TH className="text-right">Qty</TH><TH>By</TH><TH className="hidden md:table-cell">Why</TH></TR>
          </THead>
          <TBody>
            {actions.map((r) => (
              <TR key={r.id} data-testid="action-row">
                <TD><Link className="font-medium hover:underline" href={`/products/${r.product_id}`}>{r.sku}</Link><div className="text-xs text-muted-foreground md:hidden">{r.reason}</div></TD>
                <TD><HealthBadge health={r.health} /></TD>
                <TD><ActionBadge action={r.action} /></TD>
                <TD className="text-right tabular-nums">{fmtNum(r.qty)}</TD>
                <TD className="whitespace-nowrap">{fmtDate(r.order_by_date)}</TD>
                <TD className="hidden max-w-xl text-xs text-muted-foreground md:table-cell">{r.reason}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
      <p className="mt-3 text-sm"><Link className="underline" href="/recommendations">All recommendations →</Link></p>
    </>
  );
}
