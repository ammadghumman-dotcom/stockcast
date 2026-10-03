"use client";

import { useAuth } from "@clerk/nextjs";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import { type ApiClient, type TokenGetter } from "@stockcast/shared";

import { clientFor, DEFAULT_ORG_ID, ORG_COOKIE } from "./api";
import { clerkEnabled } from "./auth";

type OrgCtx = {
  /** Org id for header mode; Clerk's active org id (or null = none selected) in Clerk mode. */
  orgId: string | null;
  setOrgId: (id: string) => void;
  api: ApiClient;
  /** Auth headers for raw `fetch` calls (multipart upload, file download). */
  authHeaders: () => Promise<Record<string, string>>;
  mode: "clerk" | "header";
  role: "owner" | "admin" | "viewer";
};

const Ctx = createContext<OrgCtx | null>(null);

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : null;
}

export function OrgProvider({ children, initialOrgId }: { children: React.ReactNode; initialOrgId?: string | null }) {
  return clerkEnabled ? <ClerkOrgProvider>{children}</ClerkOrgProvider> : <HeaderOrgProvider initialOrgId={initialOrgId}>{children}</HeaderOrgProvider>;
}

function HeaderOrgProvider({ children, initialOrgId }: { children: React.ReactNode; initialOrgId?: string | null }) {
  const [orgId, setOrg] = useState<string>(() => initialOrgId ?? readCookie(ORG_COOKIE) ?? DEFAULT_ORG_ID);
  const setOrgId = useCallback((id: string) => {
    setOrg(id);
    document.cookie = `${ORG_COOKIE}=${encodeURIComponent(id)}; path=/; max-age=31536000; samesite=lax`;
  }, []);
  const api = useMemo(() => clientFor(orgId), [orgId]);
  const authHeaders = useCallback(async () => ({ "X-Org-Id": orgId }), [orgId]);
  return <Ctx.Provider value={{ orgId, setOrgId, api, authHeaders, mode: "header", role: "owner" }}>{children}</Ctx.Provider>;
}

const CLERK_ROLES: Record<string, OrgCtx["role"]> = { "org:owner": "owner", "org:admin": "admin", "org:member": "viewer" };

function ClerkOrgProvider({ children }: { children: React.ReactNode }) {
  const { getToken, orgId, orgRole } = useAuth();
  // Keep one client instance per org; the token getter reads through a ref so a Clerk
  // re-render (token refresh) never recreates the client or refires queries.
  const tokenRef = useRef<TokenGetter>(async () => null);
  useEffect(() => {
    tokenRef.current = () => getToken();
  }, [getToken]);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- new client (and query keys) per active org
  const api = useMemo(() => clientFor(null, () => tokenRef.current()), [orgId]);
  const setOrgId = useCallback(() => {
    /* Clerk owns the active organization (use the OrganizationSwitcher). */
  }, []);
  const authHeaders = useCallback(async (): Promise<Record<string, string>> => {
    const token = await tokenRef.current();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, []);
  const role = CLERK_ROLES[orgRole ?? ""] ?? "viewer";
  return <Ctx.Provider value={{ orgId: orgId ?? null, setOrgId, api, authHeaders, mode: "clerk", role }}>{children}</Ctx.Provider>;
}

export function useOrg(): OrgCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useOrg outside OrgProvider");
  return v;
}

export function useApi(): ApiClient {
  return useOrg().api;
}
