import type { Metadata } from "next";
import Link from "next/link";

import { ProductionTicket } from "@/components/marketing/production-ticket";
import { WaitlistForm } from "@/components/marketing/waitlist-form";
import { BETA_DISCOUNT, PUBLIC_PLANS, TRIAL_DAYS, betaPrice, limitLabel } from "@/lib/plans";
import { site } from "@/lib/site";

const title = "Stockcast: demand forecasting and raw-material planning for multichannel brands";
const description =
  "Forecast sales across Shopify, Amazon, eBay and WooCommerce, then turn them into raw-material and packaging orders through your bill of materials. Built for brands that make what they sell.";

export const metadata: Metadata = {
  title,
  description,
  alternates: { canonical: "/" },
  keywords: [
    "demand forecasting",
    "inventory forecasting",
    "raw material planning",
    "bill of materials",
    "multichannel inventory",
    "Shopify inventory forecasting",
    "Amazon FBA forecasting",
    "purchase orders",
  ],
  openGraph: { title, description, url: "/", siteName: site.name, type: "website" },
  twitter: { card: "summary_large_image", title, description },
};

const steps = [
  {
    title: "Connect your channels",
    body: "Install the Shopify app or connect Amazon, eBay and WooCommerce. Up to two years of orders and current stock import in minutes, or start from CSV files.",
  },
  {
    title: "Forecast every product",
    body: "Each SKU gets a daily forecast with a likely range, adjusted for holidays like Christmas, Eid and Diwali and for your own promotions, and split by channel.",
  },
  {
    title: "Plan materials and order",
    body: "Your bill of materials turns product forecasts into wax, jars, fabric or packaging. You get order-by dates that respect supplier lead times and minimum orders, and purchase orders ready to send.",
  },
];

const features = [
  {
    title: "One forecast across every channel",
    body: "Sales from all your stores are combined per product, then split back out so you can see how much Amazon needs versus your own site.",
  },
  {
    title: "Raw materials, not just finished goods",
    body: "Multi-level bills of materials: a gift set uses candles, and candles use wax and wicks. Components are planned with their own lead times.",
  },
  {
    title: "Holidays and promotions built in",
    body: "Uplift is learned from your own history for each category and region. Every adjusted day shows why: “Christmas” or “promo: Spring Sale”.",
  },
  {
    title: "Reorder or produce, with a reason",
    body: "Each recommendation says whether to buy or make, how much, by when, and the stock-out date if you do nothing.",
  },
  {
    title: "Accuracy you can check",
    body: "Every run is back-tested on your last four weeks of sales, so you can see how close the forecast would have been.",
  },
  {
    title: "Purchase orders in a click",
    body: "Recommendations become draft POs grouped by supplier. Export as PDF or CSV, or email them straight to the supplier.",
  },
];

const jsonLd = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: site.name,
  applicationCategory: "BusinessApplication",
  operatingSystem: "Web",
  url: site.url,
  description,
  offers: PUBLIC_PLANS.map((p) => ({
    "@type": "Offer",
    name: p.name,
    price: p.priceUsd,
    priceCurrency: "USD",
    category: "subscription",
  })),
};

export default function LandingPage() {
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />

      {/* Hero */}
      <section className="mx-auto grid max-w-6xl gap-12 px-4 pb-20 pt-14 sm:px-6 lg:grid-cols-[1.05fr_1fr] lg:items-center lg:pt-20">
        <div>
          <h1 className="mk-display text-[2.6rem] font-semibold leading-[1.05] sm:text-6xl" data-testid="hero-headline">
            Know what to make and what to order before you run out.
          </h1>
          <p className="mt-6 max-w-[56ch] text-lg leading-relaxed text-[var(--mk-ink-soft)]">
            Stockcast forecasts demand across Shopify, Amazon, eBay and WooCommerce, then works out the
            wax, jars, fabric and packaging you need through your bill of materials, with order-by dates
            that respect each supplier&apos;s lead time.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link
              href="/sign-up"
              className="rounded-md bg-[var(--mk-pine)] px-5 py-3 font-medium text-white hover:bg-[var(--mk-pine-dark)]"
              data-testid="cta-trial"
            >
              Start {TRIAL_DAYS}-day free trial
            </Link>
            <Link
              href="#beta"
              className="rounded-md border border-[var(--mk-ink)] px-5 py-3 font-medium hover:bg-[var(--mk-panel)]"
            >
              Apply for the beta
            </Link>
          </div>
          <p className="mt-4 text-sm text-[var(--mk-ink-soft)]">No card needed. Works with CSV files if your store isn&apos;t connected yet.</p>
        </div>
        <ProductionTicket />
      </section>

      {/* Who it's for */}
      <section className="bg-[var(--mk-panel)]">
        <div className="mx-auto grid max-w-6xl gap-8 px-4 py-16 sm:px-6 md:grid-cols-[1fr_1.4fr]">
          <h2 className="mk-display text-3xl font-semibold leading-tight">
            For brands that make what they sell
          </h2>
          <div className="text-lg leading-relaxed text-[var(--mk-ink-soft)]">
            <p>
              Inventory apps count finished goods. If you pour candles, fill bottles or cut and sew,
              the item that runs out first is usually a component with a six-week lead time. Stockcast
              plans those too, from the same forecast.
            </p>
            <ul className="mt-6 grid gap-x-8 gap-y-3 text-base text-[var(--mk-ink)] sm:grid-cols-3">
              <li>
                <strong className="block">Candles and home fragrance</strong>
                wax, wicks, jars, oils
              </li>
              <li>
                <strong className="block">Cosmetics and skincare</strong>
                bases, actives, bottles, labels
              </li>
              <li>
                <strong className="block">Apparel and accessories</strong>
                fabric, trims, packaging
              </li>
            </ul>
          </div>
        </div>
      </section>

      {/* How it works — a real sequence, so numbered */}
      <section id="how" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6">
        <h2 className="mk-display text-3xl font-semibold">How it works</h2>
        <ol className="mt-10 grid gap-10 md:grid-cols-3">
          {steps.map((s, i) => (
            <li key={s.title} className="border-t-2 border-[var(--mk-ink)] pt-5">
              <span className="mk-display text-4xl font-semibold text-[var(--mk-pine)]">{i + 1}</span>
              <h3 className="mk-display mt-3 text-xl font-semibold">{s.title}</h3>
              <p className="mt-2 leading-relaxed text-[var(--mk-ink-soft)]">{s.body}</p>
            </li>
          ))}
        </ol>
      </section>

      {/* Features */}
      <section className="border-t border-[var(--mk-line)]">
        <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
          <h2 className="mk-display max-w-[24ch] text-3xl font-semibold leading-tight">
            Everything between a sale and a supplier order
          </h2>
          <dl className="mt-12 grid gap-x-12 gap-y-10 sm:grid-cols-2 lg:grid-cols-3">
            {features.map((f) => (
              <div key={f.title}>
                <dt className="font-semibold">{f.title}</dt>
                <dd className="mt-2 leading-relaxed text-[var(--mk-ink-soft)]">{f.body}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      {/* Demo video (hidden until NEXT_PUBLIC_DEMO_VIDEO_URL is set) */}
      {site.demoVideoUrl && (
        <section id="demo" className="bg-[var(--mk-ink)] text-white">
          <div className="mx-auto max-w-5xl px-4 py-20 sm:px-6">
            <h2 className="mk-display text-3xl font-semibold">See it in three minutes</h2>
            <p className="mt-3 text-white/75">
              From connecting a store to sending a purchase order for jars.
            </p>
            <div className="mt-8 aspect-video overflow-hidden rounded-xl bg-black">
              <iframe
                src={site.demoVideoUrl}
                title="Stockcast product demo"
                className="h-full w-full"
                loading="lazy"
                allow="encrypted-media; fullscreen; picture-in-picture"
                allowFullScreen
                data-testid="demo-video"
              />
            </div>
          </div>
        </section>
      )}

      {/* Pricing */}
      <section id="pricing" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6">
        <h2 className="mk-display text-3xl font-semibold">Pricing</h2>
        <p className="mt-3 max-w-[60ch] text-[var(--mk-ink-soft)]">
          Every plan starts with a {TRIAL_DAYS}-day free trial with Growth limits. Prices are per
          month in USD. Beta brands get {BETA_DISCOUNT.percent}% off for their first{" "}
          {BETA_DISCOUNT.months} months.
        </p>
        <div className="mt-10 grid gap-6 md:grid-cols-3" data-testid="pricing-table">
          {PUBLIC_PLANS.map((p) => {
            const featured = p.id === "growth";
            return (
              <div
                key={p.id}
                className={
                  featured
                    ? "rounded-xl border-2 border-[var(--mk-ink)] p-6"
                    : "rounded-xl border border-[var(--mk-line)] p-6"
                }
              >
                <div className="flex items-baseline justify-between">
                  <h3 className="mk-display text-xl font-semibold">{p.name}</h3>
                  {featured && <span className="text-sm text-[var(--mk-pine)]">Most brands start here</span>}
                </div>
                <p className="mt-1 text-sm text-[var(--mk-ink-soft)]">{p.blurb}</p>
                <p className="mt-5">
                  <span className="mk-display text-4xl font-semibold">${p.priceUsd}</span>
                  <span className="text-[var(--mk-ink-soft)]"> /month</span>
                </p>
                <p className="mt-1 text-sm text-[var(--mk-ink-soft)]">
                  ${betaPrice(p.priceUsd)}/month for {BETA_DISCOUNT.months} months in the beta
                </p>
                <ul className="mt-5 space-y-2 text-sm">
                  <li>{limitLabel(p.channels, "sales channel")}</li>
                  <li>{limitLabel(p.skus, "SKU")}</li>
                  {p.features.map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                </ul>
                <Link
                  href="/sign-up"
                  className={
                    featured
                      ? "mt-6 block rounded-md bg-[var(--mk-pine)] px-4 py-2.5 text-center font-medium text-white hover:bg-[var(--mk-pine-dark)]"
                      : "mt-6 block rounded-md border border-[var(--mk-ink)] px-4 py-2.5 text-center font-medium hover:bg-[var(--mk-panel)]"
                  }
                >
                  Start free trial
                </Link>
              </div>
            );
          })}
        </div>
      </section>

      {/* Beta */}
      <section id="beta" className="scroll-mt-20 bg-[var(--mk-panel)]">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 py-20 sm:px-6 lg:grid-cols-[1fr_1.3fr]">
          <div>
            <h2 className="mk-display text-3xl font-semibold leading-tight">Join the beta</h2>
            <p className="mt-4 leading-relaxed text-[var(--mk-ink-soft)]">
              We&apos;re working closely with ten brands that make or assemble their products and sell
              on two or more channels. Beta brands get {BETA_DISCOUNT.percent}% off for{" "}
              {BETA_DISCOUNT.months} months, help setting up their bills of materials, and a direct
              line to the people building Stockcast.
            </p>
          </div>
          <WaitlistForm />
        </div>
      </section>
    </>
  );
}
