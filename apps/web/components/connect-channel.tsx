"use client";

import { useState } from "react";

import { unwrap } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import { useApi } from "@/lib/org";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, NativeSelect } from "@/components/ui/input";

type Kind = "amazon" | "ebay" | "woocommerce" | "csv";

export const AMAZON_MARKETPLACES: Record<string, string> = {
  ATVPDKIKX0DER: "United States",
  A2EUQ1WTGCTBG2: "Canada",
  A1AM78C64UM0Y8: "Mexico",
  A1F83G8C2ARO7P: "United Kingdom",
  A1PA6795UKMFR9: "Germany",
  A13V1IB3VIYZZH: "France",
  APJ6JRA9NG5V4: "Italy",
  A1RKKUPIHCS9HS: "Spain",
  A2VIGQ35RCS4UG: "UAE",
  A17E79C6D8DWNP: "Saudi Arabia",
  A21TJRUUN4KGV: "India",
  A1VC38T7YXB528: "Japan",
  A39IBJ37TRP1C6: "Australia",
};
export const EBAY_MARKETPLACES = ["EBAY_US", "EBAY_GB", "EBAY_DE", "EBAY_AU", "EBAY_CA", "EBAY_FR", "EBAY_IT", "EBAY_ES"];

/** Which fields a channel type needs; mirrors CREDENTIAL_KEYS on the API. */
export function requiredFields(kind: Kind, mode: "oauth" | "manual"): string[] {
  if (kind === "woocommerce") return ["url", "consumer_key", "consumer_secret"];
  if (kind === "csv" || mode === "oauth") return [];
  return ["refresh_token"];
}

export function ConnectChannelDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const api = useApi();
  const [kind, setKind] = useState<Kind>("amazon");
  const [mode, setMode] = useState<"oauth" | "manual">("oauth");
  const [name, setName] = useState("");
  const [market, setMarket] = useState("ATVPDKIKX0DER");
  const [creds, setCreds] = useState<Record<string, string>>({});
  const reset = () => { setName(""); setCreds({}); setMode("oauth"); };

  const connect = useAction(
    async () => {
      const external_shop_id = kind === "amazon" || kind === "ebay" ? market : kind === "woocommerce" ? creds.url : undefined;
      const manual = mode === "manual" || kind === "woocommerce";
      const credentials = manual && kind !== "csv" ? { ...creds, ...(kind !== "woocommerce" ? { marketplace_id: market } : {}) } : undefined;
      const ch = unwrap(await api.POST("/channels", { body: { name: name || defaultName(kind, market), type: kind, external_shop_id, credentials } }));
      if (!manual && (kind === "amazon" || kind === "ebay")) {
        const path = kind === "amazon" ? "/amazon/install" : "/ebay/install";
        const { url } = unwrap(await api.GET(path, { params: { query: { channel_id: ch.id } } }));
        window.location.href = url;
      }
      return ch;
    },
    { success: (ch) => `${ch.name} added`, invalidate: ["channels"], onSuccess: () => { onOpenChange(false); reset(); } },
  );
  const fields = requiredFields(kind, mode);
  const ready = fields.every((f) => (creds[f] ?? "").trim().length > 0);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Connect a sales channel">
        <Field label="Channel">
          <NativeSelect value={kind} onChange={(e) => { setKind(e.target.value as Kind); setCreds({}); setMarket(e.target.value === "ebay" ? "EBAY_US" : "ATVPDKIKX0DER"); }} data-testid="channel-kind">
            <option value="amazon">Amazon (Seller Central)</option>
            <option value="ebay">eBay</option>
            <option value="woocommerce">WooCommerce</option>
            <option value="csv">CSV uploads</option>
          </NativeSelect>
        </Field>
        <Field label="Name"><Input placeholder={defaultName(kind, market)} value={name} onChange={(e) => setName(e.target.value)} data-testid="channel-name" /></Field>
        {kind === "amazon" ? (
          <Field label="Marketplace">
            <NativeSelect value={market} onChange={(e) => setMarket(e.target.value)}>
              {Object.entries(AMAZON_MARKETPLACES).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </NativeSelect>
          </Field>
        ) : null}
        {kind === "ebay" ? (
          <Field label="Marketplace">
            <NativeSelect value={market} onChange={(e) => setMarket(e.target.value)}>
              {EBAY_MARKETPLACES.map((m) => <option key={m} value={m}>{m.replace("EBAY_", "eBay ")}</option>)}
            </NativeSelect>
          </Field>
        ) : null}
        {kind === "amazon" || kind === "ebay" ? (
          <div className="flex gap-2 text-xs">
            <button type="button" className={`rounded border px-2 py-1 ${mode === "oauth" ? "bg-primary text-primary-foreground" : ""}`} onClick={() => setMode("oauth")}>Sign in with {kind === "amazon" ? "Amazon" : "eBay"}</button>
            <button type="button" className={`rounded border px-2 py-1 ${mode === "manual" ? "bg-primary text-primary-foreground" : ""}`} onClick={() => setMode("manual")} data-testid="mode-manual">Paste a refresh token</button>
          </div>
        ) : null}
        {fields.map((f) => (
          <Field key={f} label={LABELS[f] ?? f}>
            <Input type={f.includes("secret") || f.includes("token") ? "password" : "text"} placeholder={PLACEHOLDERS[f]} value={creds[f] ?? ""} onChange={(e) => setCreds((c) => ({ ...c, [f]: e.target.value }))} data-testid={`cred-${f}`} />
          </Field>
        ))}
        <Button loading={connect.isPending} disabled={!ready} onClick={() => connect.mutate()} data-testid="connect-channel">
          {mode === "oauth" && (kind === "amazon" || kind === "ebay") ? `Continue to ${kind === "amazon" ? "Amazon" : "eBay"}` : "Connect"}
        </Button>
        <p className="text-xs text-muted-foreground">Credentials are stored encrypted and never shown again. The first sync backfills two years of orders.</p>
      </DialogContent>
    </Dialog>
  );
}

function defaultName(kind: Kind, market: string): string {
  if (kind === "amazon") return `Amazon ${AMAZON_MARKETPLACES[market] ?? market}`;
  if (kind === "ebay") return market.replace("EBAY_", "eBay ");
  if (kind === "woocommerce") return "WooCommerce";
  return "CSV uploads";
}

const LABELS: Record<string, string> = { url: "Store URL", consumer_key: "Consumer key", consumer_secret: "Consumer secret", refresh_token: "Refresh token" };
const PLACEHOLDERS: Record<string, string> = { url: "https://shop.example.com", consumer_key: "ck_…", consumer_secret: "cs_…", refresh_token: "Atzr|… / v^1.1#…" };
