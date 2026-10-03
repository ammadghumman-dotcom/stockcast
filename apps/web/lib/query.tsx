"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { Toaster } from "sonner";

import { OrgProvider } from "./org";

export function Providers({ children, initialOrgId }: { children: React.ReactNode; initialOrgId?: string | null }) {
  const [qc] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false } },
      }),
  );
  return (
    <QueryClientProvider client={qc}>
      <OrgProvider initialOrgId={initialOrgId}>
        {children}
        <Toaster richColors position="bottom-right" closeButton />
      </OrgProvider>
    </QueryClientProvider>
  );
}
