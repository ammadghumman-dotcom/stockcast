import { describe, expect, it } from "vitest";

import { daysFromToday, fmtDate, fmtMoney, fmtNum } from "@/lib/utils";

describe("formatters", () => {
  it("fmtNum handles strings, nulls and digits", () => {
    expect(fmtNum("75000.0000")).toBe("75,000");
    expect(fmtNum(null)).toBe("–");
    expect(fmtNum("abc")).toBe("–");
    expect(fmtNum(4.2, 2)).toBe("4.2");
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
