import { describe, expect, it } from "vitest";

import { poEditBody } from "../lib/po";

const lines = [{ id: "a", qty: "1144.0000" }, { id: "b", qty: 269 }];

describe("draft PO edits", () => {
  it("sends only changed quantities", () => {
    expect(poEditBody(lines, { a: "1200", b: "269" })).toEqual({ body: { lines: { a: "1200" } } });
    expect(poEditBody(lines, {})).toEqual({ body: null });
    expect(poEditBody(lines, { a: "" })).toEqual({ body: null });
  });

  it("0 removes a line but not the last one; negatives are refused", () => {
    expect(poEditBody(lines, { b: "0" })).toEqual({ body: { lines: { b: "0" } } });
    expect(poEditBody(lines, { a: "0", b: "0" })).toEqual({ error: "Keep at least one line on the PO" });
    expect(poEditBody(lines, { a: "-5" })).toEqual({ error: "Quantities must be 0 or more" });
  });
});
