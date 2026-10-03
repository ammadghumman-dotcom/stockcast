import type { Health } from "@stockcast/shared";

const API_URL = process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function fetchHealth(): Promise<Health | null> {
  try {
    const res = await fetch(`${API_URL}/health`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as Health;
  } catch {
    return null;
  }
}
