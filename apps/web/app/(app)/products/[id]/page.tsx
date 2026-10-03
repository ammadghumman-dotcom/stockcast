"use client";

import { useParams } from "next/navigation";
import { useMemo } from "react";

import { unwrap } from "@/lib/api";
import { useOrgQuery, useRecommendations, useSuppliers } from "@/lib/hooks";
import { useApi } from "@/lib/org";
import { fmtDate, fmtNum } from "@/lib/utils";
import { PageHeader } from "@/components/shell";
import { ChannelSplit } from "@/components/channel-mix";
import { ForecastChart, type ChartPoint } from "@/components/charts/forecast-chart";
import { ActionBadge, HealthBadge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, Tile } from "@/components/ui/card";
import { Empty } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export default function ProductDetail() {
  const { id } = useParams<{ id: string }>();
  const api = useApi();
  const product = useOrgQuery(["product", id], async () => unwrap(await api.GET("/products/{product_id}", { params: { path: { product_id: id } } })));
  const sales = useOrgQuery(["sales", id], async () => unwrap(await api.GET("/products/{product_id}/sales", { params: { path: { product_id: id }, query: { days: 180 } } })));
  const forecast = useOrgQuery(["forecast", id], async () => {
    const r = await api.GET("/forecasts", { params: { query: { product_id: id, days: 90 } } });
    return r.response.status === 404 ? null : unwrap(r);
  });
  const inventory = useOrgQuery(["inventory", id], async () => unwrap(await api.GET("/products/{product_id}/inventory", { params: { path: { product_id: id } } })));
  const bom = useOrgQuery(["bom", id], async () => unwrap(await api.GET("/bom-lines", { params: { query: { parent_product_id: id } } })));
  const products = useOrgQuery(["products"], async () => unwrap(await api.GET("/products", { params: { query: { limit: 500 } } })));
  const recs = useRecommendations({ product_id: id });
  const suppliers = useSuppliers();
  const rec = recs.data?.[0];

  const chart = useMemo<ChartPoint[]>(() => {
    const pts: ChartPoint[] = (sales.data ?? []).map((s) => ({ date: s.date, actual: Number(s.units) }));
    for (const p of forecast.data?.points ?? []) {
      pts.push({ date: p.date, p10: Number(p.p10), p50: Number(p.p50), p90: Number(p.p90), band: [Number(p.p10), Number(p.p90)], event: p.event });
    }
    return pts.sort((a, b) => a.date.localeCompare(b.date));
  }, [sales.data, forecast.data]);

  const nameOf = (pid: string) => products.data?.find((p) => p.id === pid);

  if (product.isLoading) return <Skeleton className="h-40" />;
  if (!product.data) return <Empty title="Product not found" action={{ label: "Back to products", href: "/products" }} />;
  const p = product.data;

  return (
    <>
      <PageHeader title={`${p.sku} — ${p.name}`} sub={`${p.type.replace("_", " ")} · sold per ${p.unit} · unit cost ${fmtNum(p.unit_cost, 4)}`} />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile label="Health" value={<HealthBadge health={rec?.health} />} />
        <Tile label="On hand" value={fmtNum(rec?.on_hand)} sub={rec ? `${fmtNum(rec.inbound)} inbound` : undefined} />
        <Tile label="Days of cover" value={rec ? (rec.days_of_cover ?? "90+") : "–"} sub={rec?.stockout_date ? `runs out ${fmtDate(rec.stockout_date)}` : undefined} tone={rec?.days_of_cover != null && rec.days_of_cover < 14 ? "warn" : undefined} />
        <Tile label="Next action" value={<ActionBadge action={rec?.action} />} sub={rec && rec.action !== "none" ? `${fmtNum(rec.qty)} by ${fmtDate(rec.order_by_date)}` : undefined} />
      </div>
      {rec ? <p className="mb-4 rounded-md border bg-muted/40 p-3 text-sm" data-testid="reason">{rec.reason}</p> : null}

      <Tabs defaultValue="forecast">
        <TabsList>
          <TabsTrigger value="forecast">Forecast</TabsTrigger>
          <TabsTrigger value="inventory">Inventory</TabsTrigger>
          <TabsTrigger value="bom">BOM</TabsTrigger>
        </TabsList>
        <TabsContent value="forecast">
          <Card>
            <CardHeader><CardTitle>Sales history and 90-day forecast {forecast.data ? <span className="text-xs font-normal text-muted-foreground">· model {forecast.data.model} · 30d p50 {fmtNum(forecast.data.total_p50_30d)}</span> : null}</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              {sales.isLoading || forecast.isLoading ? <Skeleton className="h-72" /> : chart.length ? <ForecastChart data={chart} asOf={forecast.data?.as_of} /> : <Empty title="No sales or forecast yet" />}
              {forecast.data ? (
                <div>
                  <h3 className="mb-2 text-sm font-medium">Channel mix <span className="text-xs font-normal text-muted-foreground">· share of the last 90 days, applied to the combined forecast</span></h3>
                  <ChannelSplit channels={forecast.data.channels ?? []} />
                </div>
              ) : null}
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="inventory">
          {inventory.isLoading ? <Skeleton className="h-24" /> : !inventory.data?.length ? <Empty title="No stock recorded" /> : (
            <Table>
              <THead><TR><TH>Location</TH><TH className="text-right">On hand</TH><TH className="text-right">Inbound</TH></TR></THead>
              <TBody>{inventory.data.map((i) => <TR key={i.location_id}><TD>{i.location_name}</TD><TD className="text-right tabular-nums">{fmtNum(i.on_hand)}</TD><TD className="text-right tabular-nums">{fmtNum(i.inbound)}</TD></TR>)}</TBody>
            </Table>
          )}
        </TabsContent>
        <TabsContent value="bom">
          {bom.isLoading ? <Skeleton className="h-24" /> : !bom.data?.length ? <Empty title="No bill of materials" body="Add BOM lines via CSV import or the API to plan raw materials for this product." /> : (
            <Table>
              <THead><TR><TH>Component</TH><TH className="text-right">Qty per unit</TH><TH>Supplier</TH></TR></THead>
              <TBody>
                {bom.data.map((l) => {
                  const c = nameOf(l.component_product_id);
                  const sup = suppliers.data?.find((s) => s.id === c?.preferred_supplier_id);
                  return (
                    <TR key={l.id}>
                      <TD><a className="hover:underline" href={`/products/${l.component_product_id}`}>{c?.sku ?? l.component_product_id.slice(0, 8)}</a> <span className="text-xs text-muted-foreground">{c?.name}</span></TD>
                      <TD className="text-right tabular-nums">{fmtNum(l.qty_per_unit, 2)} {c?.unit}</TD>
                      <TD className="text-xs text-muted-foreground">{sup?.name ?? "–"}</TD>
                    </TR>
                  );
                })}
              </TBody>
            </Table>
          )}
        </TabsContent>
      </Tabs>
    </>
  );
}
