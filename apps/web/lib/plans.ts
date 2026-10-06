/** Public price list. Mirrors apps/api/app/billing/plans.py (PLANS) — change both together. */
export type PublicPlan = {
  id: "starter" | "growth" | "scale";
  name: string;
  priceUsd: number;
  channels: number | null; // null = unlimited
  skus: number | null;
  blurb: string;
  features: string[];
};

export const TRIAL_DAYS = 14;
export const BETA_DISCOUNT = { percent: 50, months: 6 } as const;

export const PUBLIC_PLANS: PublicPlan[] = [
  {
    id: "starter",
    name: "Starter",
    priceUsd: 39,
    channels: 1,
    skus: 500,
    blurb: "One store, a focused catalogue.",
    features: ["Daily forecasts and reorder points", "Raw-material planning", "Purchase orders"],
  },
  {
    id: "growth",
    name: "Growth",
    priceUsd: 99,
    channels: 3,
    skus: 5_000,
    blurb: "Selling on Shopify, Amazon and more.",
    features: [
      "Everything in Starter",
      "Demand split by channel",
      "Holiday and promotion planning",
      "Team members and roles",
    ],
  },
  {
    id: "scale",
    name: "Scale",
    priceUsd: 249,
    channels: null,
    skus: null,
    blurb: "Many channels and large catalogues.",
    features: ["Everything in Growth", "Unlimited channels and SKUs", "Priority support"],
  },
];

export function limitLabel(n: number | null, noun: string): string {
  if (n === null) return `Unlimited ${noun}s`;
  return `${n.toLocaleString("en-US")} ${noun}${n === 1 ? "" : "s"}`;
}

export function betaPrice(priceUsd: number): number {
  return Math.round((priceUsd * (100 - BETA_DISCOUNT.percent)) / 100);
}
