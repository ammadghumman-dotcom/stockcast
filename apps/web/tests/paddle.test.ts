import { describe, expect, it } from "vitest";

import { providerNote } from "@/components/billing";
import { paddleEnv, successUrl, transactionId } from "@/lib/paddle";

describe("paddle pay page helpers", () => {
  it("accepts only Paddle transaction ids", () => {
    expect(transactionId(new URLSearchParams("_ptxn=txn_01h8abc"))).toBe("txn_01h8abc");
    expect(transactionId(new URLSearchParams("_ptxn=javascript:alert(1)"))).toBeNull();
    expect(transactionId(new URLSearchParams(""))).toBeNull();
  });
  it("defaults to sandbox unless production is explicit", () => {
    expect(paddleEnv(undefined)).toBe("sandbox");
    expect(paddleEnv("live")).toBe("sandbox");
    expect(paddleEnv("production")).toBe("production");
  });
  it("returns to settings after paying", () => {
    expect(successUrl("https://app.stockcast.app")).toBe("https://app.stockcast.app/settings?billing=success");
  });
});

describe("providerNote", () => {
  it("names the merchant of record", () => {
    expect(providerNote("lemonsqueezy")).toContain("Lemon Squeezy, our reseller");
    expect(providerNote("paddle")).toContain("Paddle");
    expect(providerNote("stripe")).toBe(" Payments are processed by Stripe.");
    expect(providerNote(null)).toBe("");
  });
});
