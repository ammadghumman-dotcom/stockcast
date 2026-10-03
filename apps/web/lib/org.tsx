"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";

import { type ApiClient } from "@stockcast/shared";

import { clientFor, DEFAULT_ORG_ID, ORG_COOKIE } from "./api";

type OrgCtx = { orgId: string; setOrgId: (id: string) => void; api: ApiClient };

const Ctx = createContext<OrgCtx | null>(null);

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : null;
}

export function OrgProvider({ children, initialOrgId }: { children: React.ReactNode; initialOrgId?: string | null }) {
  const [orgId, setOrg] = useState<string>(() => initialOrgId ?? readCookie(ORG_COOKIE) ?? DEFAULT_ORG_ID);
  const setOrgId = useCallback((id: string) => {
    setOrg(id);
    document.cookie = `${ORG_COOKIE}=${encodeURIComponent(id)}; path=/; max-age=31536000; samesite=lax`;
  }, []);
  const api = useMemo(() => clientFor(orgId), [orgId]);
  return <Ctx.Provider value={{ orgId, setOrgId, api }}>{children}</Ctx.Provider>;
}

export function useOrg(): OrgCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useOrg outside OrgProvider");
  return v;
}

export function useApi(): ApiClient {
  return useOrg().api;
}
