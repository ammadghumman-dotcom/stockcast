import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import LandingPage, { metadata } from "@/app/(marketing)/page";
import { WaitlistForm } from "@/components/marketing/waitlist-form";
import { BETA_DISCOUNT, PUBLIC_PLANS, betaPrice, limitLabel } from "@/lib/plans";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("landing page", () => {
  it("leads with multichannel + raw-material planning and has SEO meta", () => {
    render(<LandingPage />);
    expect(screen.getByTestId("hero-headline").textContent).toMatch(/make and what to order/);
    expect(screen.getByText(/Shopify, Amazon, eBay and WooCommerce/)).toBeTruthy();
    expect(String(metadata.description)).toMatch(/raw-material/);
    expect(metadata.alternates?.canonical).toBe("/");
  });

  it("prices every plan with its beta price", () => {
    render(<LandingPage />);
    const table = screen.getByTestId("pricing-table");
    for (const p of PUBLIC_PLANS) {
      expect(table.textContent).toContain(`$${p.priceUsd}`);
      expect(table.textContent).toContain(`$${betaPrice(p.priceUsd)}/month`);
    }
  });

  it("hides the demo section until a video URL is configured", () => {
    render(<LandingPage />);
    expect(screen.queryByTestId("demo-video")).toBeNull();
  });
});

describe("plans helpers", () => {
  it("formats limits and the beta discount", () => {
    expect(limitLabel(1, "sales channel")).toBe("1 sales channel");
    expect(limitLabel(5000, "SKU")).toBe("5,000 SKUs");
    expect(limitLabel(null, "SKU")).toBe("Unlimited SKUs");
    expect(BETA_DISCOUNT.percent).toBe(50);
    expect(betaPrice(99)).toBe(50);
  });
});

describe("waitlist form", () => {
  it("posts the application and confirms beta fit", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ ok: true, beta_fit: true }), { status: 202 }));
    render(<WaitlistForm />);
    fireEvent.change(screen.getByLabelText("Work email"), { target: { value: "a@candles.co" } });
    fireEvent.click(screen.getByLabelText("Shopify"));
    fireEvent.click(screen.getByLabelText("Amazon"));
    fireEvent.click(screen.getByLabelText(/make or assemble/));
    fireEvent.submit(screen.getByTestId("waitlist-form"));
    await waitFor(() => expect(screen.getByTestId("waitlist-done")).toBeTruthy());
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body).toMatchObject({ email: "a@candles.co", channels: ["shopify", "amazon"], makes_products: true });
    expect(screen.getByText(/50% off for 6 months/)).toBeTruthy();
  });

  it("explains a rejected email", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 422 }));
    render(<WaitlistForm />);
    fireEvent.change(screen.getByLabelText("Work email"), { target: { value: "x@y.z" } });
    fireEvent.submit(screen.getByTestId("waitlist-form"));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/email address/));
  });
});
