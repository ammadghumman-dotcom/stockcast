"use client";

import { useState } from "react";

import { API_URL } from "@/lib/api";
import { BETA_DISCOUNT } from "@/lib/plans";

const CHANNELS = [
  { id: "shopify", label: "Shopify" },
  { id: "amazon", label: "Amazon" },
  { id: "ebay", label: "eBay" },
  { id: "woocommerce", label: "WooCommerce" },
  { id: "etsy", label: "Etsy" },
  { id: "wholesale", label: "Wholesale / retail" },
] as const;

type State = { kind: "idle" } | { kind: "sending" } | { kind: "done"; fit: boolean } | { kind: "error"; message: string };

export function WaitlistForm() {
  const [state, setState] = useState<State>({ kind: "idle" });

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setState({ kind: "sending" });
    try {
      const res = await fetch(`${API_URL}/waitlist`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: f.get("email"),
          company: f.get("company") || null,
          website: f.get("website") || null,
          channels: f.getAll("channels"),
          makes_products: f.get("makes_products") === "on",
          notes: f.get("notes") || null,
          fax: f.get("fax") || null,
          source: "landing",
        }),
      });
      if (res.status === 422) {
        setState({ kind: "error", message: "Check the email address and try again." });
        return;
      }
      if (res.status === 429) {
        setState({ kind: "error", message: "Too many attempts. Wait a minute and try again." });
        return;
      }
      if (!res.ok) throw new Error(String(res.status));
      const body = (await res.json()) as { beta_fit: boolean };
      setState({ kind: "done", fit: body.beta_fit });
    } catch {
      setState({ kind: "error", message: "We couldn't send your application. Try again, or email us." });
    }
  }

  if (state.kind === "done") {
    return (
      <div role="status" className="rounded-xl border border-[var(--mk-line)] bg-white p-6" data-testid="waitlist-done">
        <p className="mk-display text-xl font-semibold">Application received</p>
        <p className="mt-2 text-[var(--mk-ink-soft)]">
          {state.fit
            ? `You fit the beta. We'll email you an invite with ${BETA_DISCOUNT.percent}% off for ${BETA_DISCOUNT.months} months.`
            : "We'll email you when Stockcast opens to more brands."}
        </p>
      </div>
    );
  }

  const input =
    "mt-1 w-full rounded-md border border-[var(--mk-line)] bg-white px-3 py-2 text-[15px] placeholder:text-[#8a97a5]";

  return (
    <form onSubmit={onSubmit} className="rounded-xl border border-[var(--mk-line)] bg-white p-6" data-testid="waitlist-form">
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block text-sm font-medium sm:col-span-2">
          Work email
          <input name="email" type="email" required autoComplete="email" className={input} placeholder="you@yourbrand.com" />
        </label>
        <label className="block text-sm font-medium">
          Brand
          <input name="company" autoComplete="organization" className={input} placeholder="Wick & Wax Co." />
        </label>
        <label className="block text-sm font-medium">
          Store URL
          <input name="website" type="text" inputMode="url" className={input} placeholder="wickandwax.com" />
        </label>
      </div>

      <fieldset className="mt-5">
        <legend className="text-sm font-medium">Where do you sell?</legend>
        <div className="mt-2 flex flex-wrap gap-2">
          {CHANNELS.map((c) => (
            <label
              key={c.id}
              className="flex cursor-pointer items-center gap-2 rounded-md border border-[var(--mk-line)] px-3 py-1.5 text-sm has-[:checked]:border-[var(--mk-pine)] has-[:checked]:bg-[#e8f2ef]"
            >
              <input type="checkbox" name="channels" value={c.id} className="accent-[var(--mk-pine)]" />
              {c.label}
            </label>
          ))}
        </div>
      </fieldset>

      <label className="mt-5 flex items-start gap-2 text-sm">
        <input type="checkbox" name="makes_products" className="mt-1 accent-[var(--mk-pine)]" />
        <span>We make or assemble our own products (we buy raw materials or components)</span>
      </label>

      <label className="mt-5 block text-sm font-medium">
        What do you make? <span className="font-normal text-[var(--mk-ink-soft)]">Optional</span>
        <textarea name="notes" rows={2} maxLength={2000} className={input} placeholder="Soy candles and reed diffusers, about 120 SKUs" />
      </label>

      {/* Honeypot: hidden from people and assistive tech, bots fill it in */}
      <div aria-hidden className="absolute -left-[9999px] h-0 w-0 overflow-hidden">
        <label>
          Fax
          <input name="fax" tabIndex={-1} autoComplete="off" />
        </label>
      </div>

      {state.kind === "error" && (
        <p role="alert" className="mt-4 text-sm text-[var(--mk-alert)]">
          {state.message}
        </p>
      )}

      <button
        type="submit"
        disabled={state.kind === "sending"}
        className="mt-6 w-full rounded-md bg-[var(--mk-pine)] px-4 py-2.5 font-medium text-white hover:bg-[var(--mk-pine-dark)] disabled:opacity-60 sm:w-auto"
      >
        {state.kind === "sending" ? "Sending…" : "Apply for the beta"}
      </button>
    </form>
  );
}
