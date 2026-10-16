import { makeClient, type ApiClient, type TokenGetter } from "@stockcast/shared";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? process.env.API_URL ?? "http://localhost:8000";

export const DEFAULT_ORG_ID =
  process.env.NEXT_PUBLIC_DEFAULT_ORG_ID ?? "00000000-0000-0000-0000-00000000d3a0";

export const ORG_COOKIE = "stockcast_org";

/** Browser-side client: `X-Org-Id` (header mode) and/or a Clerk bearer token. */
export function clientFor(orgId: string | null, getToken?: TokenGetter): ApiClient {
  return makeClient({ baseUrl: API_URL, orgId, getToken });
}

/** Server-side health probe (no org). */
export async function fetchHealth() {
  try {
    const res = await fetch(`${API_URL}/health`, { cache: "no-store" });
    return res.ok ? ((await res.json()) as { status: string; service: string; version: string; env: string; time: string }) : null;
  } catch {
    return null;
  }
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** Human-readable text from a FastAPI error body's `detail`: a string, a plan-limit object
 * ({detail, plan}), or a list of validation errors ([{loc, msg}]). */
export function errorText(detail: unknown, fallback = "Something went wrong"): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail.map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : String(d)));
    return msgs.join("; ").slice(0, 300) || fallback;
  }
  if (detail && typeof detail === "object") {
    const o = detail as Record<string, unknown>;
    for (const k of ["detail", "message", "error"]) if (typeof o[k] === "string") return o[k] as string;
    return JSON.stringify(detail).slice(0, 300);
  }
  return fallback;
}

/** Unwrap an openapi-fetch result or throw a readable error for toasts. */
export function unwrap<T>(res: { data?: T; error?: unknown; response: Response }): T {
  if (res.error !== undefined || !res.response.ok) {
    const e = res.error as { detail?: unknown } | undefined;
    let msg = `${res.response.status}`;
    if (e?.detail) msg = errorText(e.detail, msg);
    throw new ApiError(res.response.status, msg);
  }
  return res.data as T;
}
