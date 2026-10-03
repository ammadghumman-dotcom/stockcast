"use client";

import type { Schemas } from "@stockcast/shared";

import { fmtNum } from "@/lib/utils";

type Part = { channel_id: string; channel_name: string; channel_type: string; share: number | string };

const TONES: Record<string, string> = {
  shopify: "bg-emerald-500",
  amazon: "bg-amber-500",
  ebay: "bg-blue-500",
  woocommerce: "bg-violet-500",
  csv: "bg-slate-400",
};

export function pct(share: number | string): number {
  return Math.round(Number(share) * 100);
}

/** Compact stacked bar: "60% Shopify / 40% Amazon". Renders nothing without a split. */
export function ChannelMixBar({ parts, className = "" }: { parts: Part[]; className?: string }) {
  if (!parts.length) return null;
  const title = parts.map((p) => `${pct(p.share)}% ${p.channel_name}`).join(" · ");
  return (
    <div className={`flex h-2 w-24 overflow-hidden rounded bg-muted ${className}`} title={title} aria-label={title} data-testid="channel-mix">
      {parts.map((p) => (
        <div key={p.channel_id} className={TONES[p.channel_type] ?? "bg-primary"} style={{ width: `${pct(p.share)}%` }} />
      ))}
    </div>
  );
}

/** Per-channel breakdown of a product forecast (share of the last 90 days x org p50). */
export function ChannelSplit({ channels }: { channels: Schemas["ChannelShare"][] }) {
  if (!channels.length) return <p className="text-xs text-muted-foreground">No channel split: demand is derived from a bill of materials or there are no sales in the last 90 days.</p>;
  return (
    <div className="space-y-2" data-testid="channel-split">
      <ChannelMixBar parts={channels} className="w-full" />
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {channels.map((c) => (
          <div key={c.channel_id} className="rounded border p-2 text-sm">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-2"><span className={`inline-block h-2 w-2 rounded-full ${TONES[c.channel_type] ?? "bg-primary"}`} />{c.channel_name}</span>
              <span className="font-medium tabular-nums">{pct(c.share)}%</span>
            </div>
            <div className="mt-1 text-xs text-muted-foreground">30d p50 {fmtNum(c.p50_30d)} · 90d p50 {fmtNum(c.p50_90d)} · last 90d sold {fmtNum(c.units_90d)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
