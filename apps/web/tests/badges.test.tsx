import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ActionBadge, HealthBadge, StatusBadge } from "@/components/ui/badge";

describe("badges", () => {
  it("maps health to label and tone", () => {
    expect(renderToStaticMarkup(<HealthBadge health="at_risk" />)).toContain("At risk");
    expect(renderToStaticMarkup(<HealthBadge health="stockout" />)).toContain("bg-red-600");
    expect(renderToStaticMarkup(<HealthBadge health={undefined} />)).toContain("–");
  });
  it("maps actions", () => {
    expect(renderToStaticMarkup(<ActionBadge action="produce" />)).toContain("Produce");
    expect(renderToStaticMarkup(<ActionBadge action="none" />)).toContain("No action");
  });
  it("maps PO status", () => {
    expect(renderToStaticMarkup(<StatusBadge status="received" />)).toContain("bg-emerald-600");
  });
});
