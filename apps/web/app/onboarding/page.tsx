"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { API_URL, unwrap } from "@/lib/api";
import { useAction, useChannels, useOrgQuery } from "@/lib/hooks";
import { useApi, useOrg } from "@/lib/org";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";

const KINDS = ["products", "bom", "inventory", "sales"] as const;

export default function Onboarding() {
  const api = useApi();
  const { orgId, setOrgId } = useOrg();
  const router = useRouter();
  const channels = useChannels();
  const [shop, setShop] = useState("");
  const [orgName, setOrgName] = useState("");
  const [files, setFiles] = useState<Partial<Record<(typeof KINDS)[number], File>>>({});
  const [result, setResult] = useState<{ kind: string; received: number; inserted: number; updated: number; errors: { row: number; message: string }[] }[] | null>(null);

  const org = useOrgQuery(["org"], async () => {
    const r = await api.GET("/orgs/me");
    return r.response.ok ? r.data! : null;
  });

  const createOrg = useAction(
    async (name: string) => unwrap(await api.POST("/orgs", { body: { name, region_code: "US", currency: "USD" } })),
    { success: (o) => `Workspace "${o.name}" created`, onSuccess: (o) => setOrgId(o.id) },
  );

  const upload = useAction(
    async () => {
      const fd = new FormData();
      for (const k of KINDS) if (files[k]) fd.append(k, files[k]!);
      const res = await fetch(`${API_URL}/imports`, { method: "POST", body: fd, headers: { "X-Org-Id": orgId } });
      if (!res.ok) throw new Error((await res.json()).detail ?? `Upload failed (${res.status})`);
      return (await res.json()) as { results: NonNullable<typeof result> };
    },
    { invalidate: ["products", "channels", "recommendations"], success: "Files imported", onSuccess: (r) => setResult(r.results) },
  );

  const runPipeline = useAction(
    async () => {
      unwrap(await api.POST("/forecast-runs", { params: { query: { horizon: 90 } } }));
      return unwrap(await api.POST("/planning-runs"));
    },
    { success: "Forecast and plan are ready", invalidate: [], onSuccess: () => router.push("/dashboard") },
  );

  const shopify = channels.data?.find((c) => c.type === "shopify");
  const syncRuns = useOrgQuery(
    ["sync-runs", shopify?.id],
    async () => unwrap(await api.GET("/channels/{channel_id}/sync-runs", { params: { path: { channel_id: shopify!.id }, query: { limit: 5 } } })),
    !!shopify,
  );
  useEffect(() => {
    if (!syncRuns.data?.some((r) => r.status === "running" || r.status === "queued")) return;
    const t = setInterval(() => syncRuns.refetch(), 3000);
    return () => clearInterval(t);
  }, [syncRuns]);

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Welcome to Stockcast</h1>
        <p className="text-sm text-muted-foreground">Connect a store or upload your data, then run your first forecast.</p>
      </div>

      <Card>
        <CardHeader><CardTitle>1. Workspace</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {org.isLoading ? <Skeleton className="h-9 w-64" /> : org.data ? (
            <p className="text-sm">Using <strong>{org.data.name}</strong> <span className="text-muted-foreground">({orgId.slice(0, 8)}…)</span></p>
          ) : (
            <p className="text-sm text-muted-foreground">No workspace selected yet.</p>
          )}
          <div className="flex gap-2">
            <Input placeholder="New workspace name" value={orgName} onChange={(e) => setOrgName(e.target.value)} data-testid="org-name" />
            <Button variant="outline" loading={createOrg.isPending} disabled={!orgName.trim()} onClick={() => createOrg.mutate(orgName.trim())} data-testid="create-org">
              Create
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>2a. Connect Shopify</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {shopify ? (
              <div className="space-y-2 text-sm">
                <p><strong>{shopify.external_shop_id}</strong> <Badge variant={shopify.is_connected ? "success" : "secondary"}>{shopify.is_connected ? "connected" : "pending"}</Badge></p>
                <div className="space-y-1">
                  {(syncRuns.data ?? []).map((r) => (
                    <div key={r.id} className="flex items-center justify-between rounded border px-2 py-1">
                      <span>{r.trigger} sync</span>
                      <span className="flex items-center gap-2">
                        {r.status === "success" ? `${r.rows_sales} sales rows` : r.error ? <span className="text-red-600">{r.error.slice(0, 60)}</span> : null}
                        <Badge variant={r.status === "success" ? "success" : r.status === "failed" ? "destructive" : "secondary"}>{r.status}</Badge>
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <>
                <Field label="Shop domain">
                  <Input placeholder="my-store.myshopify.com" value={shop} onChange={(e) => setShop(e.target.value)} />
                </Field>
                <Button asChild disabled={!shop.includes(".myshopify.com")}>
                  <a href={`${API_URL}/shopify/install?shop=${encodeURIComponent(shop)}`} onClick={(e) => { if (!shop.includes(".myshopify.com")) e.preventDefault(); }}>
                    Connect Shopify
                  </a>
                </Button>
                <p className="text-xs text-muted-foreground">Requires the Shopify app credentials to be configured on the API.</p>
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>2b. Upload CSVs</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {KINDS.map((k) => (
              <Field key={k} label={`${k}.csv`}>
                <Input type="file" accept=".csv,text/csv" data-testid={`file-${k}`} onChange={(e) => setFiles((f) => ({ ...f, [k]: e.target.files?.[0] }))} />
              </Field>
            ))}
            <Button onClick={() => upload.mutate()} loading={upload.isPending} disabled={!Object.values(files).some(Boolean)} data-testid="upload">
              Import
            </Button>
            {result ? (
              <ul className="space-y-1 text-xs" data-testid="import-result">
                {result.map((r) => (
                  <li key={r.kind}>
                    <strong>{r.kind}</strong>: {r.inserted} new, {r.updated} updated{r.errors.length ? <span className="text-red-600">, {r.errors.length} row errors (first: row {r.errors[0].row} — {r.errors[0].message})</span> : null}
                  </li>
                ))}
              </ul>
            ) : null}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle>3. Forecast & plan</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          <Button onClick={() => runPipeline.mutate()} loading={runPipeline.isPending} data-testid="run-pipeline">Run forecast and planning</Button>
          <Button variant="ghost" onClick={() => router.push("/dashboard")}>Skip to dashboard</Button>
        </CardContent>
      </Card>
    </main>
  );
}
