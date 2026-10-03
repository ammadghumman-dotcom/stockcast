"use client";

import { useState } from "react";

import type { Promotion } from "@stockcast/shared";

import { unwrap } from "@/lib/api";
import { useAction, useCategories, useChannels, useOrgQuery, useRegions } from "@/lib/hooks";
import { useApi } from "@/lib/org";
import { fmtDate, fmtNum } from "@/lib/utils";
import { PageHeader } from "@/components/shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Empty } from "@/components/ui/empty";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import { Skeleton, TableSkeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export default function CalendarPage() {
  return (
    <>
      <PageHeader title="Calendar" sub="Holidays, promotions and the demand uplift they drive" />
      <Tabs defaultValue="events">
        <TabsList><TabsTrigger value="events">Holiday events</TabsTrigger><TabsTrigger value="promotions">Promotions</TabsTrigger><TabsTrigger value="uplifts">Category uplifts</TabsTrigger></TabsList>
        <TabsContent value="events"><EventsTab /></TabsContent>
        <TabsContent value="promotions"><PromotionsTab /></TabsContent>
        <TabsContent value="uplifts"><UpliftsTab /></TabsContent>
      </Tabs>
    </>
  );
}

function EventsTab() {
  const api = useApi();
  const regions = useRegions();
  const [region, setRegion] = useState("");
  const events = useOrgQuery(["holiday-events", region], async () => unwrap(await api.GET("/holiday-events", { params: { query: { region_id: region || undefined, limit: 500 } } })));
  const [open, setOpen] = useState(false);
  const [ev, setEv] = useState({ name: "", start_date: "", end_date: "", region_id: "" });
  const add = useAction(async () => unwrap(await api.POST("/holiday-events", { body: { ...ev, region_id: ev.region_id || regions.data![0].id, recurring: false, kind: "custom" } })), { success: "Event added", invalidate: ["holiday-events"], onSuccess: () => setOpen(false) });
  const del = useAction(async (id: string) => unwrap(await api.DELETE("/holiday-events/{event_id}", { params: { path: { event_id: id } } })), { success: "Event removed", invalidate: ["holiday-events"] });
  const today = new Date().toISOString().slice(0, 10);
  const upcoming = (events.data ?? []).filter((e) => e.end_date >= today).sort((a, b) => a.start_date.localeCompare(b.start_date));
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <NativeSelect value={region} onChange={(e) => setRegion(e.target.value)} className="w-40"><option value="">All regions</option>{regions.data?.map((r) => <option key={r.id} value={r.id}>{r.code}</option>)}</NativeSelect>
        <Button variant="outline" onClick={() => setOpen(true)} disabled={!regions.data?.length} data-testid="add-event">Add custom event</Button>
      </div>
      {events.isLoading ? <TableSkeleton /> : !upcoming.length ? <Empty title="No upcoming events" body="Add a region in Settings to seed its holiday calendar." /> : (
        <Table>
          <THead><TR><TH>Event</TH><TH>Region</TH><TH>Window</TH><TH>Kind</TH><TH /></TR></THead>
          <TBody>{upcoming.map((e) => (
            <TR key={e.id}><TD className="font-medium">{e.name}</TD><TD>{regions.data?.find((r) => r.id === e.region_id)?.code}</TD><TD className="whitespace-nowrap">{fmtDate(e.start_date)} – {fmtDate(e.end_date)}</TD><TD><Badge variant={e.source === "custom" ? "info" : "outline"}>{e.source === "custom" ? "custom" : e.kind}</Badge></TD>
              <TD>{e.source === "custom" ? <Button size="sm" variant="ghost" onClick={() => del.mutate(e.id)}>Remove</Button> : null}</TD></TR>
          ))}</TBody>
        </Table>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent title="Custom event" description="Give it a lead-in window: demand usually builds before the day itself.">
          <Field label="Name"><Input value={ev.name} onChange={(e) => setEv({ ...ev, name: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-2"><Field label="Start"><Input type="date" value={ev.start_date} onChange={(e) => setEv({ ...ev, start_date: e.target.value })} /></Field><Field label="End"><Input type="date" value={ev.end_date} onChange={(e) => setEv({ ...ev, end_date: e.target.value })} /></Field></div>
          <Field label="Region"><NativeSelect value={ev.region_id} onChange={(e) => setEv({ ...ev, region_id: e.target.value })}>{regions.data?.map((r) => <option key={r.id} value={r.id}>{r.code}</option>)}</NativeSelect></Field>
          <Button loading={add.isPending} disabled={!ev.name || !ev.start_date || !ev.end_date} onClick={() => add.mutate()}>Add</Button>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function PromotionsTab() {
  const api = useApi();
  const promos = useOrgQuery(["promotions"], async () => unwrap(await api.GET("/promotions", { params: { query: { limit: 200 } } })));
  const channels = useChannels();
  const cats = useCategories();
  const [open, setOpen] = useState(false);
  const [sim, setSim] = useState<{ lift: number; post_dip: number; total_delta_units: number; products: { sku: string; delta_units: number }[]; materials: { sku: string; delta_qty: number; unit: string }[] } | null>(null);
  const blank = { name: "", type: "discount", start_date: "", end_date: "", discount_pct: "", spend_amount: "", channel_id: "", scope: "all", category_id: "" };
  const [p, setP] = useState(blank);
  const body = () => ({ name: p.name, type: p.type as Promotion["type"], start_date: p.start_date, end_date: p.end_date, discount_pct: p.discount_pct || null, spend_amount: p.spend_amount || null, channel_id: p.channel_id || null, scope: p.scope as Promotion["scope"], category_id: p.category_id || null });
  const simulate = useAction(async () => unwrap(await api.POST("/forecasts/simulate", { body: body() })), { onSuccess: (r) => setSim(r) });
  const save = useAction(
    async () => {
      const promo = unwrap(await api.POST("/promotions", { body: body() }));
      unwrap(await api.POST("/forecast-runs", { params: { query: { horizon: 90 } } }));
      unwrap(await api.POST("/planning-runs"));
      return promo;
    },
    { success: "Promotion saved — forecast and plan re-run with its uplift", invalidate: [], onSuccess: () => { setOpen(false); setP(blank); setSim(null); } },
  );
  const del = useAction(async (id: string) => unwrap(await api.DELETE("/promotions/{promotion_id}", { params: { path: { promotion_id: id } } })), { success: "Promotion removed", invalidate: ["promotions"] });
  return (
    <div className="space-y-3">
      <Button onClick={() => setOpen(true)} data-testid="add-promotion">Plan a promotion</Button>
      {promos.isLoading ? <TableSkeleton /> : !promos.data?.length ? <Empty title="No promotions" body="Plan a campaign to see its effect on the forecast and raw-material needs." /> : (
        <Table>
          <THead><TR><TH>Name</TH><TH>Type</TH><TH>Window</TH><TH className="text-right">Discount</TH><TH className="text-right">Spend</TH><TH>Observed lift</TH><TH /></TR></THead>
          <TBody>{promos.data.map((pr) => (
            <TR key={pr.id}><TD className="font-medium">{pr.name}</TD><TD><Badge variant="outline">{pr.type}</Badge></TD><TD className="whitespace-nowrap">{fmtDate(pr.start_date)} – {fmtDate(pr.end_date)}</TD><TD className="text-right">{pr.discount_pct ? `${fmtNum(pr.discount_pct)}%` : "–"}</TD><TD className="text-right">{fmtNum(pr.spend_amount)}</TD>
              <TD>{pr.observed_lift ? <span>{Number(pr.observed_lift).toFixed(2)}× <span className="text-xs text-muted-foreground">dip {Number(pr.observed_post_dip ?? 1).toFixed(2)}</span></span> : <span className="text-xs text-muted-foreground">not yet measured</span>}</TD>
              <TD><Button size="sm" variant="ghost" onClick={() => del.mutate(pr.id)}>Remove</Button></TD></TR>
          ))}</TBody>
        </Table>
      )}
      <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (!o) setSim(null); }}>
        <DialogContent title="Plan a promotion" description="Simulate first to see the unit and raw-material impact, then save to re-run the forecast." className="max-w-2xl">
          <div className="grid gap-2 md:grid-cols-2">
            <Field label="Name"><Input value={p.name} onChange={(e) => setP({ ...p, name: e.target.value })} data-testid="promo-name" /></Field>
            <Field label="Type"><NativeSelect value={p.type} onChange={(e) => setP({ ...p, type: e.target.value })}><option value="discount">Discount</option><option value="paid_ads">Paid ads</option><option value="email">Email</option></NativeSelect></Field>
            <Field label="Start"><Input type="date" value={p.start_date} onChange={(e) => setP({ ...p, start_date: e.target.value })} data-testid="promo-start" /></Field>
            <Field label="End"><Input type="date" value={p.end_date} onChange={(e) => setP({ ...p, end_date: e.target.value })} data-testid="promo-end" /></Field>
            <Field label="Discount %"><Input type="number" value={p.discount_pct} onChange={(e) => setP({ ...p, discount_pct: e.target.value })} data-testid="promo-discount" /></Field>
            <Field label="Ad spend"><Input type="number" value={p.spend_amount} onChange={(e) => setP({ ...p, spend_amount: e.target.value })} /></Field>
            <Field label="Channel"><NativeSelect value={p.channel_id} onChange={(e) => setP({ ...p, channel_id: e.target.value })}><option value="">Any</option>{channels.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</NativeSelect></Field>
            <Field label="Scope"><div className="flex gap-2"><NativeSelect value={p.scope} onChange={(e) => setP({ ...p, scope: e.target.value })}><option value="all">All products</option><option value="category">Category</option></NativeSelect>{p.scope === "category" ? <NativeSelect value={p.category_id} onChange={(e) => setP({ ...p, category_id: e.target.value })}><option value="">pick…</option>{cats.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</NativeSelect> : null}</div></Field>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" loading={simulate.isPending} disabled={!p.name || !p.start_date || !p.end_date} onClick={() => simulate.mutate()} data-testid="simulate">Simulate</Button>
            <Button loading={save.isPending} disabled={!p.name || !p.start_date || !p.end_date} onClick={() => save.mutate()} data-testid="save-promotion">Save & re-run forecast</Button>
          </div>
          {sim ? (
            <Card data-testid="sim-result">
              <CardHeader><CardTitle>Predicted lift {sim.lift.toFixed(2)}× · {fmtNum(sim.total_delta_units)} extra units (after a {((1 - sim.post_dip) * 100).toFixed(0)}% post-promo dip)</CardTitle></CardHeader>
              <CardContent className="grid gap-3 text-sm md:grid-cols-2">
                <div><p className="mb-1 text-xs text-muted-foreground">Top products</p>{sim.products.slice(0, 6).map((x) => <div key={x.sku} className="flex justify-between"><span>{x.sku}</span><span className="tabular-nums">+{fmtNum(x.delta_units)}</span></div>)}</div>
                <div><p className="mb-1 text-xs text-muted-foreground">Raw materials needed</p>{sim.materials.length ? sim.materials.map((m) => <div key={m.sku} className="flex justify-between"><span>{m.sku}</span><span className="tabular-nums">+{fmtNum(m.delta_qty)} {m.unit}</span></div>) : <span className="text-muted-foreground">none (no BOM)</span>}</div>
              </CardContent>
            </Card>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function UpliftsTab() {
  const api = useApi();
  const cats = useCategories();
  const regions = useRegions();
  const ups = useOrgQuery(["category-uplifts"], async () => unwrap(await api.GET("/category-uplifts")));
  const [edit, setEdit] = useState<Record<string, string>>({});
  const save = useAction(async ({ id, v }: { id: string; v: string }) => unwrap(await api.PATCH("/category-uplifts/{uplift_id}", { params: { path: { uplift_id: id } }, body: { uplift_pct: v } })), { success: "Uplift updated (now manual)", invalidate: ["category-uplifts"] });
  if (ups.isLoading) return <Skeleton className="h-40" />;
  if (!ups.data?.length) return <Empty title="No uplifts yet" body="Run a forecast: learned uplifts and editable priors appear here." />;
  const rows = [...ups.data].sort((a, b) => Number(b.uplift_pct) - Number(a.uplift_pct));
  return (
    <Table>
      <THead><TR><TH>Category</TH><TH>Region</TH><TH>Event</TH><TH className="text-right">Uplift %</TH><TH>Source</TH><TH /></TR></THead>
      <TBody>{rows.map((u) => (
        <TR key={u.id}>
          <TD>{cats.data?.find((c) => c.id === u.category_id)?.name ?? "–"}</TD><TD>{regions.data?.find((r) => r.id === u.region_id)?.code}</TD><TD>{u.event_name}</TD>
          <TD className="text-right"><Input className="ml-auto h-8 w-24 text-right" value={edit[u.id] ?? String(u.uplift_pct)} onChange={(e) => setEdit((x) => ({ ...x, [u.id]: e.target.value }))} /></TD>
          <TD>{u.learned ? <Badge variant="success">learned · n={u.sample_size}</Badge> : <Badge variant="outline">prior</Badge>}</TD>
          <TD>{edit[u.id] !== undefined && edit[u.id] !== String(u.uplift_pct) ? <Button size="sm" onClick={() => save.mutate({ id: u.id, v: edit[u.id] })}>Save</Button> : null}</TD>
        </TR>
      ))}</TBody>
    </Table>
  );
}
