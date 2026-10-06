import type { Metadata } from "next";

import { Doc } from "@/components/marketing/chrome";
import { site } from "@/lib/site";

export const metadata: Metadata = {
  title: "Support · Stockcast",
  description: "Get help with Stockcast: setup, syncing, forecasts, billing and data deletion.",
  alternates: { canonical: "/support" },
};

const faqs: { q: string; a: React.ReactNode }[] = [
  {
    q: "How do I connect my store?",
    a: (
      <>
        Install Stockcast from the Shopify App Store, or open <strong>Settings → Channels</strong>{" "}
        and connect Shopify, Amazon, eBay or WooCommerce. You can also upload products, sales and
        inventory as CSV files during onboarding.
      </>
    ),
  },
  {
    q: "How long until I see a forecast?",
    a: "The first sync imports up to two years of order history, usually within minutes. Forecasts and recommendations are then generated automatically and refreshed every night.",
  },
  {
    q: "Why does a product show no forecast?",
    a: "Products with fewer than a few weeks of sales use a category-based starting estimate until enough history exists. Check that the product is mapped to the right listing under Products → SKU mapping.",
  },
  {
    q: "How do I plan raw materials?",
    a: "Add a bill of materials to a finished product (for example wax, wick and jar for a candle). Stockcast converts the product forecast into demand for each component and plans those with their own lead times.",
  },
  {
    q: "How do I cancel or change my plan?",
    a: "Go to Settings → Billing. Shopify installs are billed through your Shopify invoice and can be cancelled there or by uninstalling the app.",
  },
  {
    q: "How do I delete my data?",
    a: (
      <>
        Uninstalling the Shopify app removes our access immediately and erases that shop&apos;s
        data 48 hours later. To delete a whole workspace, email{" "}
        <a href={`mailto:${site.supportEmail}`}>{site.supportEmail}</a> from the owner&apos;s
        address.
      </>
    ),
  },
];

export default function SupportPage() {
  return (
    <Doc title="Support">
      <p>
        Email <a href={`mailto:${site.supportEmail}`}>{site.supportEmail}</a> with your store URL
        and a short description. We reply within one business day (Monday–Friday). For data or
        privacy requests, see our <a href="/privacy">privacy policy</a>.
      </p>
      <h2>Frequently asked questions</h2>
      {faqs.map((f) => (
        <section key={f.q}>
          <h3 className="mt-6 font-semibold">{f.q}</h3>
          <p>{f.a}</p>
        </section>
      ))}
    </Doc>
  );
}
