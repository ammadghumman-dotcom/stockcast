import { describe, expect, it } from "vitest";

import { daysLeft, fmtLimit, planLabel } from "@/components/billing";

describe("billing helpers", () => {
  it("formats limits", () => {
    expect(fmtLimit(null)).toBe("Unlimited");
    expect(fmtLimit(5000)).toBe("5,000");
  });
  it("counts trial days left, never negative", () => {
    const now = new Date("2026-10-03T09:00:00Z");
    expect(daysLeft("2026-10-06T09:00:00Z", now)).toBe(3);
    expect(daysLeft("2026-10-01T09:00:00Z", now)).toBe(0);
    expect(daysLeft(null, now)).toBeNull();
  });
  it("labels plans and lock states", () => {
    expect(planLabel({ plan: "growth", plan_status: "active", effective_plan: "growth", trial_ends_at: null })).toBe("Growth · active");
    expect(planLabel({ plan: "growth", plan_status: "past_due", effective_plan: "growth", trial_ends_at: null })).toBe("Growth · past due");
    expect(planLabel({ plan: "trial", plan_status: "trialing", effective_plan: "locked", trial_ends_at: null })).toBe("Trial ended");
    expect(planLabel({ plan: "scale", plan_status: "canceled", effective_plan: "locked", trial_ends_at: null })).toBe("Scale · canceled");
    expect(planLabel({ plan: "trial", plan_status: "trialing", effective_plan: "trial", trial_ends_at: null })).toBe("Trial");
    expect(planLabel({ plan: "trial", plan_status: "trialing", effective_plan: "trial", trial_ends_at: null, billing_enabled: false })).toBe("Early access");
    expect(planLabel({ plan: "growth", plan_status: "active", effective_plan: "growth", trial_ends_at: null, billing_enabled: false })).toBe("Growth · active");
  });
});

describe("shared client auth", () => {
  it("sends a bearer token when a getter is given", async () => {
    const { makeClient } = await import("@stockcast/shared");
    let seen: Headers | null = null;
    const fetchStub = async (req: Request) => {
      seen = req.headers;
      return new Response("[]", { status: 200, headers: { "content-type": "application/json" } });
    };
    const c = makeClient({ baseUrl: "http://api.test", orgId: "org-1", getToken: async () => "tok", fetch: fetchStub as never });
    await c.GET("/products");
    expect(seen!.get("authorization")).toBe("Bearer tok");
    expect(seen!.get("x-org-id")).toBe("org-1");
  });
});
