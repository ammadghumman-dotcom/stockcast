import type { Metadata } from "next";

export const metadata: Metadata = { title: "Stockcast", robots: { index: false } };

/** Embedded Shopify admin shell: App Bridge nav (rendered by the admin, not in our iframe). */
export default function ShopifyLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <s-app-nav>
        <s-link href="/shopify" rel="home">
          Home
        </s-link>
        <s-link href="/shopify/recommendations">Reorder plan</s-link>
        <s-link href="/shopify/plan">Plan and billing</s-link>
      </s-app-nav>
      {children}
    </>
  );
}
