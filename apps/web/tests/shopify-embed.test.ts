import { describe, expect, it } from "vitest";

import { trialDaysLeft } from "@/components/shopify/session";
import { embeddedFrameAncestors, isEmbeddedPath, limitText, validShop } from "@/lib/shopify-embed";

describe("embedded Shopify app helpers", () => {
  it("only lets the shop's own admin frame the app", () => {
    expect(embeddedFrameAncestors("wick-and-wax.myshopify.com")).toBe(
      "https://wick-and-wax.myshopify.com https://admin.shopify.com",
    );
    for (const bad of [null, "", "evil.com", "x.myshopify.com.evil.com", "https://a.myshopify.com"]) {
      expect(embeddedFrameAncestors(bad)).toBe("'none'");
    }
    expect(validShop("a-b.myshopify.com")).toBe(true);
  });

  it("recognises embedded paths", () => {
    expect(isEmbeddedPath("/shopify")).toBe(true);
    expect(isEmbeddedPath("/shopify/plan")).toBe(true);
    expect(isEmbeddedPath("/shopifyish")).toBe(false);
    expect(isEmbeddedPath(null)).toBe(false);
  });

  it("counts trial days left", () => {
    const now = new Date("2026-10-06T12:00:00Z");
    expect(trialDaysLeft({ plan: "trial", trial_ends_at: "2026-10-16T12:00:00Z" }, now)).toBe(10);
    expect(trialDaysLeft({ plan: "trial", trial_ends_at: "2026-10-01T00:00:00Z" }, now)).toBe(0);
    expect(trialDaysLeft({ plan: "growth", trial_ends_at: null }, now)).toBeNull();
  });

  it("labels plan limits", () => {
    expect(limitText(3, "sales channel")).toBe("3 sales channels");
    expect(limitText(null, "SKU")).toBe("Unlimited SKUs");
  });
});

describe("waitForAppBridge", () => {
  it("resolves once App Bridge attaches to window, or null after the timeout", async () => {
    const { waitForAppBridge } = await import("@/lib/org");
    const fake = { idToken: async () => "tok" } as unknown as NonNullable<Window["shopify"]>;
    setTimeout(() => {
      window.shopify = fake;
    }, 60);
    expect(await waitForAppBridge(1000)).toBe(fake);
    delete window.shopify;
    expect(await waitForAppBridge(80)).toBeNull();
  });
});
