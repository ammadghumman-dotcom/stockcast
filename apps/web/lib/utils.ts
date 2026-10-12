import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function fmtNum(n: number | string | null | undefined, digits = 0): string {
  if (n === null || n === undefined || n === "") return "–";
  const v = typeof n === "string" ? Number(n) : n;
  if (Number.isNaN(v)) return "–";
  return v.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function fmtMoney(n: number | string | null | undefined, currency = "USD"): string {
  if (n === null || n === undefined || n === "") return "–";
  const v = typeof n === "string" ? Number(n) : n;
  return v.toLocaleString(undefined, { style: "currency", currency, maximumFractionDigits: 0 });
}

export function fmtDate(d: string | null | undefined): string {
  if (!d) return "–";
  const dt = new Date(d.length === 10 ? `${d}T00:00:00` : d);
  return dt.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function daysFromToday(d: string | null | undefined): number | null {
  if (!d) return null;
  const dt = new Date(`${d.slice(0, 10)}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((dt.getTime() - today.getTime()) / 86_400_000);
}

/** "Order by" label that never shows a date in the past (staging bug #9): a due date before
 * today is overdue and reads "Now · 2d late". */
export function orderByLabel(d: string | null | undefined, today: Date = new Date()): { text: string; overdue: boolean } {
  if (!d) return { text: "–", overdue: false };
  const dt = new Date(`${d.slice(0, 10)}T00:00:00`);
  const t0 = new Date(today);
  t0.setHours(0, 0, 0, 0);
  const days = Math.round((dt.getTime() - t0.getTime()) / 86_400_000);
  if (days < 0) return { text: `Now · ${-days}d late`, overdue: true };
  if (days === 0) return { text: "Today", overdue: true };
  return { text: fmtDate(d), overdue: false };
}

/** "Plan from Oct 9 · data to Oct 8": when the plan ran and the last day of sales it used. */
export function planStamp(asOf: string | null | undefined, ranAt: string | null | undefined): string | undefined {
  if (!asOf) return undefined;
  return ranAt ? `Plan from ${fmtDate(ranAt)} · sales data to ${fmtDate(asOf)}` : `Sales data to ${fmtDate(asOf)}`;
}

/** Dashboard accuracy tile (staging bug #10): a score from a handful of SKUs, or a "perfect"
 * WAPE of 0 on flat test data, is not shown as a headline 100 %. */
export const MIN_ACCURACY_SKUS = 5;
export function accuracyTile(wape: number | string | null | undefined, measured: number): { value: string; sub: string } {
  if (wape == null || measured === 0) return { value: "–", sub: "no backtest yet" };
  const w = Number(wape);
  if (measured < MIN_ACCURACY_SKUS)
    return { value: "Too early", sub: `backtested ${measured} SKU${measured === 1 ? "" : "s"}; needs ${MIN_ACCURACY_SKUS}+ with 2 months of sales` };
  const pct = Math.max(0, 1 - w) * 100;
  return { value: pct >= 99.5 ? "99%+" : `${pct.toFixed(0)}%`, sub: `WAPE ${w.toFixed(2)} on ${measured} SKUs` };
}

/** Top of a chart's y-axis: 15 % above the highest value, rounded to a readable step, so a flat
 * series doesn't sit on the frame (staging bug #27). */
export function chartTop(values: Array<number | null | undefined>): number {
  const max = Math.max(0, ...values.filter((v): v is number => typeof v === "number" && Number.isFinite(v)));
  if (max === 0) return 1;
  const raw = max * 1.15;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const lead = raw / mag; // 1 ≤ lead < 10
  const step = lead > 5 ? mag : lead > 2 ? mag / 2 : mag / 5;
  return Math.ceil(raw / step) * step;
}
