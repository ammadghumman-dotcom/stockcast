/** Helpers for the embedded Shopify app (/shopify). Pure so they can run in middleware + tests. */

const SHOP_RE = /^[a-z0-9][a-z0-9-]*\.myshopify\.com$/;

export function validShop(shop: string | null | undefined): shop is string {
  return !!shop && SHOP_RE.test(shop);
}

/** `frame-ancestors` value: only this shop's admin may frame the app; nobody when unknown. */
export function embeddedFrameAncestors(shop: string | null | undefined): string {
  return validShop(shop) ? `https://${shop} https://admin.shopify.com` : "'none'";
}

export const SHOPIFY_API_KEY = process.env.NEXT_PUBLIC_SHOPIFY_API_KEY ?? "";
export const APP_BRIDGE_SRC = "https://cdn.shopify.com/shopifycloud/app-bridge.js";
export const POLARIS_SRC = "https://cdn.shopify.com/shopifycloud/polaris.js";

export function isEmbeddedPath(pathname: string | null | undefined): boolean {
  return !!pathname && (pathname === "/shopify" || pathname.startsWith("/shopify/"));
}

export function limitText(n: number | null, noun: string): string {
  return n === null ? `Unlimited ${noun}s` : `${n.toLocaleString("en-US")} ${noun}${n === 1 ? "" : "s"}`;
}
