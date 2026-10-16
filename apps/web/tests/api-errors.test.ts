import { describe, expect, it } from "vitest";

import { errorText } from "../lib/api";

describe("errorText", () => {
  it("reads plan-limit objects, strings and validation lists", () => {
    expect(errorText({ detail: "Starter plan allows 500 SKUs. Upgrade to add more.", plan: "starter" })).toBe(
      "Starter plan allows 500 SKUs. Upgrade to add more.",
    );
    expect(errorText("only drafts can be edited")).toBe("only drafts can be edited");
    expect(errorText([{ loc: ["body", "qty"], msg: "must be >= 0" }, { msg: "name required" }])).toBe("must be >= 0; name required");
    expect(errorText(undefined, "Upload failed (500)")).toBe("Upload failed (500)");
  });
});
