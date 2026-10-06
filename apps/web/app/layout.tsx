import { ClerkProvider } from "@clerk/nextjs";
import type { Metadata } from "next";
import { cookies } from "next/headers";

import { Analytics } from "@/components/analytics";
import { ORG_COOKIE } from "@/lib/api";
import { clerkEnabled } from "@/lib/auth";
import { site } from "@/lib/site";
import { Providers } from "@/lib/query";

import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(site.url),
  title: "Stockcast",
  description: "AI demand forecasting and raw-material planning for ecommerce brands",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const jar = await cookies();
  const initialOrgId = jar.get(ORG_COOKIE)?.value ?? null;
  const page = (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <Providers initialOrgId={initialOrgId}>{children}</Providers>
        <Analytics />
      </body>
    </html>
  );
  return clerkEnabled ? <ClerkProvider
      afterSignOutUrl="/"
      signInFallbackRedirectUrl="/dashboard"
      signUpFallbackRedirectUrl="/onboarding"
    >{page}</ClerkProvider> : page;
}
