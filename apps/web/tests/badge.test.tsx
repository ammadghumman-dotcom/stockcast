import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { Badge } from "@/components/ui/badge";

describe("Badge", () => {
  it("renders success variant", () => {
    const html = renderToStaticMarkup(<Badge variant="success">Online</Badge>);
    expect(html).toContain("Online");
    expect(html).toContain("bg-emerald-600");
  });
});
