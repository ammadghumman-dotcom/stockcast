import { describe, expect, it } from "vitest";

import { daysFromToday, fmtDate, fmtMoney, fmtNum, orderByLabel, planStamp, accuracyTile, chartTop } from "@/lib/utils";

describe("formatters", () => {
  it("fmtNum handles strings, nulls and digits", () => {
    expect(fmtNum("75000.0000")).toBe("75,000");
    expect(fmtNum(null)).toBe("–");
    expect(fmtNum("abc")).toBe("–");
    expect(fmtNum(4.2, 2)).toBe("4.2");
    expect(fmtNum("0.2270", 4)).toBe("0.227"); // BOM quantities keep 3+ decimals (#26)
  });
  it("fmtMoney uses currency", () => {
    expect(fmtMoney("49650.82")).toMatch(/\$49,651/);
    expect(fmtMoney(0, "GBP")).toMatch(/£0/);
  });
  it("fmtDate reads ISO dates without timezone drift", () => {
    expect(fmtDate("2026-10-03")).toMatch(/Oct 3/);
    expect(fmtDate(null)).toBe("–");
  });
  it("daysFromToday", () => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    expect(daysFromToday(iso(today))).toBe(0);
    const plus3 = new Date(today.getTime() + 3 * 86_400_000);
    expect(daysFromToday(iso(plus3))).toBe(3);
    expect(daysFromToday(null)).toBeNull();
  });
});

describe("order-by dates (#9)", () => {
  const today = new Date("2026-10-09T10:00:00");
  it("never shows a past date", () => {
    expect(orderByLabel("2026-10-08", today)).toEqual({ text: "Now · 1d late", overdue: true });
    expect(orderByLabel("2026-10-09", today)).toEqual({ text: "Today", overdue: true });
    expect(orderByLabel("2026-10-15", today).overdue).toBe(false);
    expect(orderByLabel(null, today).text).toBe("–");
  });
  it("plan stamp names both the run day and the data day", () => {
    expect(planStamp("2026-10-08", "2026-10-09T04:30:00Z")).toMatch(/^Plan from .* · sales data to /);
    expect(planStamp(null, null)).toBeUndefined();
  });
});

describe("accuracy tile (#10)", () => {
  it("does not headline 100% from a few SKUs", () => {
    expect(accuracyTile("0.0000", 3)).toEqual({ value: "Too early", sub: "backtested 3 SKUs; needs 5+ with 2 months of sales" });
    expect(accuracyTile("0.0010", 12).value).toBe("99%+");
    expect(accuracyTile("0.3873", 20)).toEqual({ value: "61%", sub: "WAPE 0.39 on 20 SKUs" });
    expect(accuracyTile(null, 0).value).toBe("–");
  });
});

describe("chart headroom (#27)", () => {
  it("leaves room above a flat line", () => {
    expect(chartTop([20, 20, 20])).toBeGreaterThan(20);
    expect(chartTop([20, 20, 20])).toBeLessThanOrEqual(30);
    expect(chartTop([0, null, undefined])).toBe(1);
    expect(chartTop([3.4, 9.9, 7])).toBeGreaterThanOrEqual(11.3);
  });
});
