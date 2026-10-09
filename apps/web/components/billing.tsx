"use client";

import { useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { toast } from "sonner";

import type { Billing, PlanInfo } from "@stockcast/shared";

import { unwrap } from "@/lib/api";
import { useAction, useOrgQuery } from "@/lib/hooks";
import { useApi, useOrg } from "@/lib/org";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export function fmtLimit(n: number | null | undefined): string {
  return n == null ? "Unlimited" : n.toLocaleString();
}

export function daysLeft(iso: string | null | undefined, now = new Date()): number | null {
  if (!iso) return null;
  return Math.max(0, Math.ceil((new Date(iso).getTime() - now.getTime()) / 86_400_000));
}

export function planLabel(
  b: Pick<Billing, "plan" | "plan_status" | "effective_plan" | "trial_ends_at"> & { billing_enabled?: boolean },
): string {
  if (b.billing_enabled === false && b.plan === "trial") return "Early access";
  if (b.effective_plan === "locked") return b.plan === "trial" ? "Trial ended" : `${cap(b.plan)} · ${b.plan_status}`;
  if (b.plan === "trial") {
    const d = daysLeft(b.trial_ends_at);
    return d == null ? "Trial" : `Trial · ${d} day${d === 1 ? "" : "s"} left`;
  }
  return `${cap(b.plan)} · ${b.plan_status.replace("_", " ")}`;
}

function cap(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function BillingTab() {
  const api = useApi();
  const { role } = useOrg();
  const params = useSearchParams();
  const q = useOrgQuery(["billing"], async () => unwrap(await api.GET("/billing")));
  useEffect(() => {
    const r = params.get("billing");
    if (r === "success") toast.success("Subscription active — thanks!");
    if (r === "cancelled") toast.info("Checkout cancelled");
  }, [params]);
  const checkout = useAction(
    async (plan: string) => unwrap(await api.POST("/billing/checkout", { body: { plan } })),
    { onSuccess: (r) => { window.location.href = r.url; } },
  );
  const portal = useAction(async () => unwrap(await api.POST("/billing/portal")), {
    onSuccess: (r) => { window.location.href = r.url; },
  });
  if (q.isLoading || !q.data) return <Skeleton className="h-48" />;
  const b = q.data;
  const canManage = role === "owner" || role === "admin";
  const locked = b.effective_plan === "locked";
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            Current plan <Badge variant={locked ? "destructive" : "secondary"} data-testid="plan-badge">{planLabel(b)}</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {!b.billing_enabled ? (
            <p className="text-sm text-muted-foreground" data-testid="billing-disabled">
              Paid plans open soon. Everything is free during early access, with {b.plan === "trial" ? "Growth" : "your plan's"} limits below.
            </p>
          ) : null}
          {locked ? (
            <p className="text-sm text-amber-700">
              Nothing new can be added until you pick a plan. Existing data stays readable.
            </p>
          ) : null}
          <div className="grid gap-3 sm:grid-cols-2">
            <Usage label="Sales channels" used={b.usage.channels} limit={b.limits.channels} />
            <Usage label="SKUs" used={b.usage.skus} limit={b.limits.skus} />
          </div>
          {b.has_subscription && canManage ? (
            <Button variant="outline" loading={portal.isPending} onClick={() => portal.mutate(undefined)} data-testid="manage-billing">
              Manage billing (invoices, card, cancel)
            </Button>
          ) : null}
          {b.billing_email ? <p className="text-xs text-muted-foreground">Billing email: {b.billing_email}</p> : null}
        </CardContent>
      </Card>
      <div className="grid gap-3 md:grid-cols-3">
        {b.plans.map((p) => (
          <PlanCard key={p.key} plan={p} current={b.plan === p.key && !locked} canManage={canManage && b.billing_enabled} busy={checkout.isPending} onPick={() => checkout.mutate(p.key)} />
        ))}
      </div>
      <p className="text-xs text-muted-foreground">All plans include nightly forecasts, holiday & promotion uplift, raw-material planning, purchase orders and email alerts.{b.billing_enabled ? " 14-day free trial, cancel any time." : ""}</p>
    </div>
  );
}

function Usage({ label, used, limit }: { label: string; used: number; limit: number | null | undefined }) {
  const pct = limit ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  const over = limit != null && used >= limit;
  return (
    <div className="rounded-md border p-3">
      <div className="flex justify-between text-sm"><span>{label}</span><span className={over ? "font-medium text-red-600" : ""}>{used.toLocaleString()} / {fmtLimit(limit)}</span></div>
      {limit ? <div className="mt-2 h-1.5 rounded bg-muted"><div className={`h-1.5 rounded ${over ? "bg-red-500" : "bg-primary"}`} style={{ width: `${pct}%` }} /></div> : null}
    </div>
  );
}

function PlanCard({ plan, current, canManage, busy, onPick }: { plan: PlanInfo; current: boolean; canManage: boolean; busy: boolean; onPick: () => void }) {
  return (
    <Card className={current ? "border-primary" : ""} data-testid={`plan-${plan.key}`}>
      <CardHeader><CardTitle className="flex items-baseline justify-between">{plan.name}<span className="text-base font-normal">${plan.price_usd}<span className="text-xs text-muted-foreground">/mo</span></span></CardTitle></CardHeader>
      <CardContent className="space-y-2 text-sm">
        <p>{fmtLimit(plan.channels)} sales channel{plan.channels === 1 ? "" : "s"}</p>
        <p>{fmtLimit(plan.skus)} SKUs</p>
        {current ? <Badge variant="secondary">Current plan</Badge> : canManage ? (
          <Button size="sm" loading={busy} onClick={onPick}>{plan.price_usd >= 99 ? "Upgrade" : "Choose"} {plan.name}</Button>
        ) : null}
      </CardContent>
    </Card>
  );
}
