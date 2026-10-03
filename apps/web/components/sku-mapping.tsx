"use client";

import { useState } from "react";

import type { Channel, Schemas } from "@stockcast/shared";

import { unwrap } from "@/lib/api";
import { useAction, useOrgQuery } from "@/lib/hooks";
import { useApi } from "@/lib/org";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Empty } from "@/components/ui/empty";
import { NativeSelect } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";

type Match = Schemas["MatchResult"];

export function scoreTone(score: number): "success" | "secondary" | "outline" {
  return score >= 85 ? "success" : score >= 60 ? "secondary" : "outline";
}

/** Match a channel's listings to catalog products: fuzzy suggestions + manual override. */
export function SkuMapping({ channels }: { channels: Channel[] }) {
  const api = useApi();
  const [channelId, setChannelId] = useState(channels[0]?.id ?? "");
  const [picks, setPicks] = useState<Record<string, string>>({});
  const matches = useOrgQuery(["listings-match", channelId], async () =>
    unwrap(await api.POST("/listings/match", { body: { channel_id: channelId, only_unmatched: true, limit: 5 } })), !!channelId);
  const products = useOrgQuery(["products-all"], async () => unwrap(await api.GET("/products", { params: { query: { limit: 500 } } })));
  const override = useAction(
    async ({ listing_id, product_id }: { listing_id: string; product_id: string }) =>
      unwrap(await api.POST("/listings/{listing_id}/override", { params: { path: { listing_id } }, body: { product_id } })),
    { success: (r) => (r.deleted_product ? "Listing mapped; duplicate product merged" : "Listing mapped"), invalidate: ["listings-match", "products", "products-all", "recommendations"] },
  );
  if (!channels.length) return <Empty title="No channels" body="Connect a channel first; its listings appear here for mapping." />;
  const rows: Match[] = matches.data ?? [];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <NativeSelect className="w-56" value={channelId} onChange={(e) => setChannelId(e.target.value)} data-testid="mapping-channel">
          {channels.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.type})</option>)}
        </NativeSelect>
        <p className="text-xs text-muted-foreground">Listings whose product is only used by this channel. Pick the catalog product it really is; sales and stock move with it.</p>
      </div>
      {matches.isLoading ? <Skeleton className="h-32" /> : !rows.length ? <Empty title="Nothing to map" body="Every listing on this channel already shares a product with another channel or was mapped by hand." /> : (
        <Table>
          <THead><TR><TH>Listing</TH><TH>Currently</TH><TH>Suggested match</TH><TH /></TR></THead>
          <TBody>
            {rows.map((m) => {
              const best = m.suggestions[0];
              const chosen = picks[m.listing.id] ?? best?.product_id ?? "";
              return (
                <TR key={m.listing.id} data-testid="mapping-row">
                  <TD className="text-xs"><div className="font-medium">{m.listing.external_sku ?? m.listing.external_id}</div><div className="text-muted-foreground">{m.listing.external_id}</div></TD>
                  <TD className="text-xs"><div>{m.listing.product_sku}</div><div className="text-muted-foreground">{m.listing.product_name}</div></TD>
                  <TD>
                    <div className="flex items-center gap-2">
                      <NativeSelect className="w-64" value={chosen} onChange={(e) => setPicks((p) => ({ ...p, [m.listing.id]: e.target.value }))} data-testid="mapping-pick">
                        <option value="">— keep as its own product —</option>
                        {m.suggestions.map((s) => <option key={s.product_id} value={s.product_id}>{s.sku} · {s.name} ({s.score}%)</option>)}
                        <optgroup label="All products">
                          {(products.data ?? []).filter((p) => p.id !== m.listing.product_id && !m.suggestions.some((s) => s.product_id === p.id)).map((p) => <option key={p.id} value={p.id}>{p.sku} · {p.name}</option>)}
                        </optgroup>
                      </NativeSelect>
                      {best ? <Badge variant={scoreTone(best.score)}>{best.score}% {best.reason}</Badge> : null}
                    </div>
                  </TD>
                  <TD><Button size="sm" disabled={!chosen} loading={override.isPending} onClick={() => override.mutate({ listing_id: m.listing.id, product_id: chosen })} data-testid="mapping-apply">Map</Button></TD>
                </TR>
              );
            })}
          </TBody>
        </Table>
      )}
    </div>
  );
}
