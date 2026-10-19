import { describe, expect, it } from "vitest";

import { defaultSelection, inviteSummary, stars } from "@/lib/beta";

describe("staff beta helpers", () => {
  it("pre-selects fits that were not invited yet", () => {
    const rows = [
      { email: "a@x.co", beta_fit: true, invited_at: null },
      { email: "b@x.co", beta_fit: true, invited_at: "2026-10-01T00:00:00Z" },
      { email: "c@x.co", beta_fit: false, invited_at: null },
    ];
    expect([...defaultSelection(rows)]).toEqual(["a@x.co"]);
  });
  it("summarises invite results", () => {
    expect(inviteSummary({ sent: ["a"], skipped: ["b"], failed: [], unknown: [] })).toEqual({ text: "1 invite sent · 1 already invited (not re-sent)", ok: true });
    expect(inviteSummary({ sent: [], skipped: [], failed: ["x@y.co"], unknown: [] }).ok).toBe(false);
    expect(inviteSummary({ sent: [], skipped: [], failed: [], unknown: [] }).text).toBe("Nothing to send");
  });
  it("renders ratings", () => {
    expect(stars(4)).toBe("★★★★☆");
    expect(stars(null)).toBe("–");
  });
});
