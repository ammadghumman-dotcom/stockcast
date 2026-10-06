import { ClerkProvider } from "@clerk/nextjs";
import type { Metadata } from "next";
import { cookies, headers } from "next/headers";

import { Analytics } from "@/components/analytics";
import { ORG_COOKIE } from "@/lib/api";
import { clerkEnabled } from "@/lib/auth";
import { site } from "@/lib/site";
import { EmbeddedProviders, Providers } from "@/lib/query";
import { APP_BRIDGE_SRC, POLARIS_SRC, SHOPIFY_API_KEY, isEmbeddedPath } from "@/lib/shopify-embed";

import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(site.url),
  title: "Stockcast",
  description: "AI demand forecasting and raw-material planning for ecommerce brands",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  if (isEmbeddedPath((await headers()).get("x-pathname"))) {
    // Inside the Shopify admin: App Bridge must be the first script in <head>; no Clerk.
    return (
      <html lang="en">
        <head>
          <meta name="shopify-api-key" content={SHOPIFY_API_KEY} />
          {/* eslint-disable-next-line @next/next/no-sync-scripts -- App Bridge requires a blocking script */}
          <script src={APP_BRIDGE_SRC} />
          {/* eslint-disable-next-line @next/next/no-sync-scripts -- Polaris web components */}
          <script src={POLARIS_SRC} />
        </head>
        <body>
          <EmbeddedProviders>{children}</EmbeddedProviders>
        </body>
      </html>
    );
  }
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
