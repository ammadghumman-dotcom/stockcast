"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import type { PlanningSettings, Supplier } from "@stockcast/shared";

import { unwrap } from "@/lib/api";
import { useAction, useCategories, useChannels, useOrgQuery, useRegions, useSuppliers } from "@/lib/hooks";
import { useApi, useOrg } from "@/lib/org";
import { canEdit, INVITE_ROLES, memberActions } from "@/lib/team";
import { BillingTab } from "@/components/billing";
import { ConnectChannelDialog } from "@/components/connect-channel";
import { SkuMapping } from "@/components/sku-mapping";
import { PageHeader } from "@/components/shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Empty } from "@/components/ui/empty";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export default function SettingsPage() {
  return (
    <Suspense>
      <SettingsTabs />
    </Suspense>
  );
}

function SettingsTabs() {
  const params = useSearchParams();
  const initial = params.get("tab") ?? (params.get("billing") ? "billing" : "planning");
  return (
    <>
      <PageHeader title="Settings" />
      <Tabs defaultValue={initial}>
        <TabsList className="flex-wrap">
          <TabsTrigger value="planning">Planning</TabsTrigger>
          <TabsTrigger value="suppliers">Suppliers</TabsTrigger>
          <TabsTrigger value="channels">Channels & regions</TabsTrigger>
          <TabsTrigger value="categories">Categories</TabsTrigger>
          <TabsTrigger value="team">Team</TabsTrigger>
          <TabsTrigger value="billing" data-testid="tab-billing">Billing</TabsTrigger>
        </TabsList>
        <TabsContent value="planning"><PlanningTab /></TabsContent>
        <TabsContent value="suppliers"><SuppliersTab /></TabsContent>
        <TabsContent value="channels"><ChannelsTab /></TabsContent>
        <TabsContent value="categories"><CategoriesTab /></TabsContent>
        <TabsContent value="team"><TeamTab /></TabsContent>
        <TabsContent value="billing"><BillingTab /></TabsContent>
      </Tabs>
    </>
  );
}

function PlanningTab() {
  const api = useApi();
  const q = useOrgQuery(["planning-settings"], async () => unwrap(await api.GET("/planning-settings")));
  const [form, setForm] = useState<Partial<PlanningSettings> | null>(null);
  const save = useAction(async (body: Partial<PlanningSettings>) => unwrap(await api.PATCH("/planning-settings", { body: body as never })), { success: "Planning settings saved", invalidate: ["planning-settings"] });
  if (q.isLoading || !q.data) return <Skeleton className="h-40" />;
  const v = { ...q.data, ...form };
  const num = (k: keyof PlanningSettings, label: string, step = 1) => (
    <Field key={k} label={label}>
      <Input type="number" step={step} value={String(v[k] ?? "")} onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.value }))} data-testid={`setting-${k}`} />
    </Field>
  );
  return (
    <Card>
      <CardHeader><CardTitle>Org defaults</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 md:grid-cols-3">
          {num("service_level", "Service level (0.5–0.999)", 0.01)}
          {num("target_cover_days", "Target cover (days)")}
          {num("overstock_days", "Overstock threshold (days)")}
          {num("default_lead_time_days", "Default lead time (days)")}
          {num("production_lead_time_days", "Production lead time (days)")}
          {num("at_risk_buffer_days", "At-risk buffer (days)")}
          {num("horizon_days", "Planning horizon (days)")}
        </div>
        <Button loading={save.isPending} disabled={!form} onClick={() => save.mutate(form!)} data-testid="save-planning">Save</Button>
        <p className="text-xs text-muted-foreground">Per-product overrides (lead time, cover, service level, preferred supplier) are set from the product page via the API.</p>
      </CardContent>
    </Card>
  );
}

function SuppliersTab() {
  const api = useApi();
  const suppliers = useSuppliers();
  const [open, setOpen] = useState(false);
  const [edit, setEdit] = useState<Partial<Supplier>>({});
  const save = useAction(
    async (s: Partial<Supplier>) =>
      s.id
        ? unwrap(await api.PATCH("/suppliers/{supplier_id}", { params: { path: { supplier_id: s.id } }, body: s as never }))
        : unwrap(await api.POST("/suppliers", { body: s as never })),
    { success: "Supplier saved", invalidate: ["suppliers"], onSuccess: () => setOpen(false) },
  );
  const f = (k: keyof Supplier, label: string, type = "text") => (
    <Field label={label}><Input type={type} value={String(edit[k] ?? "")} onChange={(e) => setEdit((x) => ({ ...x, [k]: type === "number" ? Number(e.target.value) : e.target.value }))} data-testid={`supplier-${k}`} /></Field>
  );
  return (
    <div className="space-y-3">
      <Button onClick={() => { setEdit({ lead_time_days: 14, moq: 1, currency: "USD" }); setOpen(true); }} data-testid="add-supplier">Add supplier</Button>
      {suppliers.isLoading ? <Skeleton className="h-32" /> : !suppliers.data?.length ? <Empty title="No suppliers" body="Add suppliers to get purchase-order recommendations with lead times and MOQs." /> : (
        <Table>
          <THead><TR><TH>Name</TH><TH>Email</TH><TH className="text-right">Lead (d)</TH><TH className="text-right">MOQ</TH><TH>Currency</TH><TH /></TR></THead>
          <TBody>{suppliers.data.map((s) => (
            <TR key={s.id}><TD className="font-medium">{s.name}</TD><TD className="text-xs">{s.email ?? "–"}</TD><TD className="text-right">{s.lead_time_days}</TD><TD className="text-right">{s.moq}</TD><TD>{s.currency}</TD>
              <TD><Button size="sm" variant="ghost" onClick={() => { setEdit(s); setOpen(true); }}>Edit</Button></TD></TR>
          ))}</TBody>
        </Table>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent title={edit.id ? "Edit supplier" : "New supplier"}>
          {f("name", "Name")}{f("email", "Email", "email")}
          <div className="grid grid-cols-3 gap-2">{f("lead_time_days", "Lead time (days)", "number")}{f("moq", "MOQ", "number")}{f("currency", "Currency")}</div>
          <Button loading={save.isPending} disabled={!edit.name} onClick={() => save.mutate(edit)} data-testid="save-supplier">Save</Button>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ChannelsTab() {
  const api = useApi();
  const channels = useChannels();
  const regions = useRegions();
  const [code, setCode] = useState("");
  const [connectOpen, setConnectOpen] = useState(false);
  const sync = useAction(
    async (id: string) => unwrap(await api.POST("/channels/{channel_id}/sync", { params: { path: { channel_id: id } } })),
    { success: "Sync started", invalidate: ["channels", "sync-runs"] },
  );
  const addRegion = useAction(async () => unwrap(await api.POST("/regions", { body: { code: code.toUpperCase(), name: code.toUpperCase(), currency: "USD" } })), { success: "Region added with its holiday calendar", invalidate: ["regions", "holiday-events"], onSuccess: () => setCode("") });
  const setRegion = useAction(
    async ({ id, region_id }: { id: string; region_id: string | null }) => unwrap(await api.PATCH("/channels/{channel_id}", { params: { path: { channel_id: id } }, body: { region_id } })),
    { success: "Channel region updated", invalidate: ["channels"] },
  );
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card>
        <CardHeader><CardTitle>Regions</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2"><Input placeholder="e.g. UK, AE, PK" value={code} onChange={(e) => setCode(e.target.value)} className="w-32" data-testid="region-code" /><Button variant="outline" disabled={code.length < 2} loading={addRegion.isPending} onClick={() => addRegion.mutate()} data-testid="add-region">Add</Button></div>
          <div className="flex flex-wrap gap-2">{regions.data?.map((r) => <Badge key={r.id} variant="secondary">{r.code} · {r.currency}</Badge>)}</div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="flex items-center justify-between">Channels <Button size="sm" variant="outline" onClick={() => setConnectOpen(true)} data-testid="add-channel">Add channel</Button></CardTitle></CardHeader>
        <CardContent>
          {!channels.data?.length ? <Empty title="No channels" body="Connect Amazon, eBay, WooCommerce or upload CSVs." /> : (
            <div className="space-y-2">{channels.data.map((c) => (
              <div key={c.id} className="flex flex-wrap items-center justify-between gap-2 rounded border p-2 text-sm" data-testid="channel-row">
                <span className="flex items-center gap-2">{c.name} <Badge variant="outline">{c.type}</Badge> <Badge variant={c.is_connected ? "success" : "secondary"}>{c.is_connected ? "connected" : c.type === "csv" ? "uploads" : "not connected"}</Badge></span>
                <span className="flex items-center gap-2">
                  {c.is_connected && c.type !== "csv" ? <Button size="sm" variant="ghost" loading={sync.isPending} onClick={() => sync.mutate(c.id)}>Sync now</Button> : null}
                  <NativeSelect className="w-28" value={c.region_id ?? ""} onChange={(e) => setRegion.mutate({ id: c.id, region_id: e.target.value || null })}>
                    <option value="">no region</option>{regions.data?.map((r) => <option key={r.id} value={r.id}>{r.code}</option>)}
                  </NativeSelect>
                </span>
              </div>
            ))}</div>
          )}
        </CardContent>
      </Card>
      <Card className="md:col-span-2">
        <CardHeader><CardTitle>SKU mapping</CardTitle></CardHeader>
        <CardContent>{channels.isLoading ? <Skeleton className="h-24" /> : <SkuMapping channels={channels.data ?? []} />}</CardContent>
      </Card>
      <ConnectChannelDialog open={connectOpen} onOpenChange={setConnectOpen} />
    </div>
  );
}

function CategoriesTab() {
  const api = useApi();
  const cats = useCategories();
  const [name, setName] = useState("");
  const add = useAction(async () => unwrap(await api.POST("/product-categories", { body: { name } })), { success: "Category added", invalidate: ["product-categories"], onSuccess: () => setName("") });
  return (
    <Card>
      <CardHeader><CardTitle>Product categories</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <div className="flex gap-2"><Input placeholder="New category" value={name} onChange={(e) => setName(e.target.value)} className="max-w-xs" /><Button variant="outline" disabled={!name.trim()} loading={add.isPending} onClick={() => add.mutate()}>Add</Button></div>
        <div className="flex flex-wrap gap-2">{cats.data?.map((c) => <Badge key={c.id} variant="secondary">{c.name}</Badge>)}</div>
        <p className="text-xs text-muted-foreground">Category names drive holiday priors (candle, gift, beauty, perfume, apparel, electronics, toy, food).</p>
      </CardContent>
    </Card>
  );
}

function TeamTab() {
  const api = useApi();
  const { role, mode } = useOrg();
  const users = useOrgQuery(["users"], async () => unwrap(await api.GET("/users")));
  const me = useOrgQuery(["me"], async () => unwrap(await api.GET("/me")));
  const blank = { email: "", name: "", role: "viewer" };
  const [u, setU] = useState(blank);
  const invite = useAction(async () => unwrap(await api.POST("/users", { body: u })), {
    success: mode === "clerk" ? "Invitation sent" : "Member added",
    invalidate: ["users"],
    onSuccess: () => setU(blank),
  });
  const remove = useAction(
    async (id: string) => unwrap(await api.DELETE("/users/{user_id}", { params: { path: { user_id: id } } })),
    { success: "Member removed", invalidate: ["users"] },
  );
  const setRole = useAction(
    async ({ id, to }: { id: string; to: string }) =>
      unwrap(await api.PATCH("/users/{user_id}", { params: { path: { user_id: id } }, body: { role: to } })),
    { success: "Role updated", invalidate: ["users", "me"] },
  );
  const myEmail = me.data?.email ?? null;
  return (
    <Card>
      <CardHeader><CardTitle>Team members</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {canEdit(role) ? (
          <div className="grid gap-2 md:grid-cols-4" data-testid="invite-form">
            <Input placeholder="Email" value={u.email} onChange={(e) => setU({ ...u, email: e.target.value })} />
            <Input placeholder="Name" value={u.name} onChange={(e) => setU({ ...u, name: e.target.value })} />
            <NativeSelect value={u.role} onChange={(e) => setU({ ...u, role: e.target.value })}>
              {INVITE_ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
            </NativeSelect>
            <Button variant="outline" disabled={!u.email || !u.name} loading={invite.isPending} onClick={() => invite.mutate()}>Invite</Button>
          </div>
        ) : null}
        {users.isLoading ? <Skeleton className="h-16" /> : !users.data?.length ? <Empty title="No members yet" /> : (
          <Table><THead><TR><TH>Name</TH><TH>Email</TH><TH>Role</TH><TH /></TR></THead>
            <TBody>{users.data.map((m) => {
              const can = memberActions(role, myEmail, m);
              return (
                <TR key={m.id}>
                  <TD>{m.name}</TD>
                  <TD className="text-xs">{m.email}</TD>
                  <TD className="space-x-1">
                    {can.canChangeRole ? (
                      <NativeSelect aria-label={`Role for ${m.email}`} value={m.role} onChange={(e) => setRole.mutate({ id: m.id, to: e.target.value })}>
                        {INVITE_ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                      </NativeSelect>
                    ) : <Badge variant="outline">{m.role}</Badge>}
                    {m.status === "invited" ? <Badge variant="outline">invited</Badge> : null}
                  </TD>
                  <TD className="space-x-1 text-right">
                    {can.canMakeOwner ? <Button size="sm" variant="ghost" onClick={() => setRole.mutate({ id: m.id, to: "owner" })}>Make owner</Button> : null}
                    {can.canRemove ? <Button size="sm" variant="ghost" onClick={() => remove.mutate(m.id)}>{m.status === "invited" ? "Revoke" : "Remove"}</Button> : null}
                  </TD>
                </TR>
              );
            })}</TBody>
          </Table>
        )}
        <p className="text-xs text-muted-foreground">
          The owner can&apos;t be removed; hand ownership to someone else first. Invited people get an email and join when they sign up.
        </p>
      </CardContent>
    </Card>
  );
}
