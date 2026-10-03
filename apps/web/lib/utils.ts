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
