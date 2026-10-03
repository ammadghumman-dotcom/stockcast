"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { unwrap } from "./api";
import { useApi, useOrg } from "./org";

/** Query helper: keys are namespaced by org so switching orgs never shows stale data. */
export function useOrgQuery<T>(key: unknown[], fn: () => Promise<T>, enabled = true) {
  const { orgId } = useOrg();
  return useQuery({ queryKey: [orgId, ...key], queryFn: fn, enabled });
}

export function useInvalidate() {
  const qc = useQueryClient();
  const { orgId } = useOrg();
  return (...prefixes: string[]) =>
    Promise.all(
      prefixes.length
        ? prefixes.map((p) => qc.invalidateQueries({ queryKey: [orgId, p] }))
        : [qc.invalidateQueries({ queryKey: [orgId] })],
    );
}

/** Mutation with toast on error and optional success message + invalidation. */
export function useAction<TArgs, TRes>(
  fn: (args: TArgs) => Promise<TRes>,
  opts: { success?: string | ((r: TRes) => string); invalidate?: string[]; onSuccess?: (r: TRes) => void } = {},
) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: fn,
    onSuccess: async (r) => {
      if (opts.invalidate) await invalidate(...opts.invalidate);
      if (opts.success) toast.success(typeof opts.success === "function" ? opts.success(r) : opts.success);
      opts.onSuccess?.(r);
    },
    onError: (e: Error) => toast.error(e.message || "Something went wrong"),
  });
}

// ---- common queries ----
export function useLatestPlanningRun() {
  const api = useApi();
  return useOrgQuery(["planning-runs", "latest"], async () => {
    const runs = unwrap(await api.GET("/planning-runs", { params: { query: { limit: 1 } } }));
    return runs.find((r) => r.status === "success") ?? runs[0] ?? null;
  });
}

export function useRecommendations(query: Record<string, string | undefined> = {}) {
  const api = useApi();
  const q = Object.fromEntries(Object.entries(query).filter(([, v]) => v));
  return useOrgQuery(["recommendations", q], async () =>
    unwrap(await api.GET("/recommendations", { params: { query: q as never } })),
  );
}

export function useProducts() {
  const api = useApi();
  return useOrgQuery(["products"], async () =>
    unwrap(await api.GET("/products", { params: { query: { limit: 500 } } })),
  );
}

export function useSuppliers() {
  const api = useApi();
  return useOrgQuery(["suppliers"], async () => unwrap(await api.GET("/suppliers", { params: { query: { limit: 500 } } })));
}

export function useCategories() {
  const api = useApi();
  return useOrgQuery(["product-categories"], async () => unwrap(await api.GET("/product-categories")));
}

export function useRegions() {
  const api = useApi();
  return useOrgQuery(["regions"], async () => unwrap(await api.GET("/regions")));
}

export function useChannels() {
  const api = useApi();
  return useOrgQuery(["channels"], async () => unwrap(await api.GET("/channels", { params: { query: { limit: 100 } } })));
}
