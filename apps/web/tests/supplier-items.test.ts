import { describe, expect, it } from "vitest";

import { emptyItem, fmtPrice, itemBody, toItemForm } from "@/lib/supplier-items";

describe("itemBody", () => {
  const ok = { ...emptyItem, product_id: "p1", price: "3.25", pack_size: "20" };

  it("builds the API body; blank lead time means 'use the supplier's'", () => {
    expect(itemBody(ok)).toEqual({ body: { product_id: "p1", price: "3.25", pack_size: 20, lead_time_days: null } });
    expect(itemBody({ ...ok, lead_time_days: "7" })).toMatchObject({ body: { lead_time_days: 7 } });
  });

  it("rejects bad input with a readable message", () => {
    expect(itemBody({ ...ok, product_id: "" })).toEqual({ error: "Pick a product" });
    expect(itemBody({ ...ok, price: "" })).toHaveProperty("error");
    expect(itemBody({ ...ok, price: "-1" })).toHaveProperty("error");
    expect(itemBody({ ...ok, pack_size: "0" })).toHaveProperty("error");
    expect(itemBody({ ...ok, pack_size: "2.5" })).toHaveProperty("error");
    expect(itemBody({ ...ok, lead_time_days: "400" })).toHaveProperty("error");
  });

  it("round-trips an API row into the form", () => {
    const f = toItemForm({ product_id: "p1", price: "3.2500", pack_size: 20, lead_time_days: null });
    expect(f).toEqual({ product_id: "p1", price: "3.25", pack_size: "20", lead_time_days: "" });
    expect(itemBody(f)).toMatchObject({ body: { price: "3.25", pack_size: 20 } });
  });
});

describe("fmtPrice", () => {
  it("shows money with 2-4 decimals", () => {
    expect(fmtPrice("3.1000")).toBe("3.10");
    expect(fmtPrice("0.0525")).toBe("0.0525");
    expect(fmtPrice("x")).toBe("–");
  });
});
