import { describe, expect, it } from "vitest";

import { overridePatch, toForm } from "../lib/planning";

const before = toForm({ preferred_supplier_id: null, lead_time_days: 12, target_cover_days: null, service_level: "0.950" });

describe("product planning overrides", () => {
  it("maps API values to the form, blanks for defaults", () => {
    expect(before).toEqual({ preferred_supplier_id: "", lead_time_days: "12", target_cover_days: "", service_level: "0.95" });
  });

  it("sends only changed fields; blank means back to the default", () => {
    const r = overridePatch(before, { ...before, preferred_supplier_id: "s1", lead_time_days: "" });
    expect(r).toEqual({ body: { preferred_supplier_id: "s1", lead_time_days: null } });
    expect(overridePatch(before, before)).toEqual({ body: {} });
  });

  it("rejects out-of-range values with a readable message", () => {
    expect(overridePatch(before, { ...before, target_cover_days: "0" })).toEqual({ error: "Target cover must be a whole number from 1 to 365" });
    expect(overridePatch(before, { ...before, lead_time_days: "2.5" })).toHaveProperty("error");
    expect(overridePatch(before, { ...before, service_level: "1" })).toEqual({ error: "Service level must be between 0.5 and 0.999" });
    expect(overridePatch(before, { ...before, service_level: "0.98" })).toEqual({ body: { service_level: "0.98" } });
  });
});
