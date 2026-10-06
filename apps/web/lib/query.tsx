"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { Toaster } from "sonner";

import { OrgProvider, ShopifyOrgProvider } from "./org";

function useQueryClient() {
  const [qc] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false } },
      }),
  );
  return qc;
}

/** Providers for the embedded Shopify app (no Clerk; App Bridge session tokens). */
export function EmbeddedProviders({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient();
  return (
    <QueryClientProvider client={qc}>
      <ShopifyOrgProvider>{children}</ShopifyOrgProvider>
    </QueryClientProvider>
  );
}

export function Providers({ children, initialOrgId }: { children: React.ReactNode; initialOrgId?: string | null }) {
  const qc = useQueryClient();
  return (
    <QueryClientProvider client={qc}>
      <OrgProvider initialOrgId={initialOrgId}>
        {children}
        <Toaster richColors position="bottom-right" closeButton />
      </OrgProvider>
    </QueryClientProvider>
  );
}
