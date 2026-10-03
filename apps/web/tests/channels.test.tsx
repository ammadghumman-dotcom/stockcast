import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ChannelMixBar, ChannelSplit, pct } from "@/components/channel-mix";
import { requiredFields } from "@/components/connect-channel";
import { scoreTone } from "@/components/sku-mapping";

describe("channel mix", () => {
  const parts = [
    { channel_id: "a", channel_name: "Shopify", channel_type: "shopify", share: "0.6000" },
    { channel_id: "b", channel_name: "Amazon US", channel_type: "amazon", share: 0.4 },
  ];
  it("rounds shares to percent", () => {
    expect(pct("0.6667")).toBe(67);
    expect(pct(0.4)).toBe(40);
  });
  it("renders a labelled stacked bar and nothing without parts", () => {
    const html = renderToStaticMarkup(<ChannelMixBar parts={parts} />);
    expect(html).toContain("60% Shopify · 40% Amazon US");
    expect(html).toContain("width:60%");
    expect(renderToStaticMarkup(<ChannelMixBar parts={[]} />)).toBe("");
  });
  it("explains an empty split", () => {
    expect(renderToStaticMarkup(<ChannelSplit channels={[]} />)).toContain("bill of materials");
  });
});

describe("connect channel", () => {
  it("knows which credentials each channel needs", () => {
    expect(requiredFields("woocommerce", "oauth")).toEqual(["url", "consumer_key", "consumer_secret"]);
    expect(requiredFields("amazon", "oauth")).toEqual([]);
    expect(requiredFields("amazon", "manual")).toEqual(["refresh_token"]);
    expect(requiredFields("csv", "manual")).toEqual([]);
  });
});

describe("sku mapping", () => {
  it("tones scores", () => {
    expect(scoreTone(92)).toBe("success");
    expect(scoreTone(70)).toBe("secondary");
    expect(scoreTone(45)).toBe("outline");
  });
});
