import type { Metadata } from "next";

import { Doc } from "@/components/marketing/chrome";
import { site } from "@/lib/site";

export const metadata: Metadata = {
  title: "Privacy policy · Stockcast",
  description: "What data Stockcast collects from your store, why, and how to have it deleted.",
  alternates: { canonical: "/privacy" },
};

export default function PrivacyPage() {
  return (
    <Doc title="Privacy policy">
      <p>
        {site.legalEntity} (&quot;Stockcast&quot;, &quot;we&quot;) provides demand forecasting and
        inventory planning software for ecommerce brands. This policy explains what we collect when
        you use Stockcast or install it on a Shopify, Amazon, eBay or WooCommerce store, and what
        we do with it.
      </p>

      <h2>What we collect</h2>
      <ul>
        <li>
          <strong>Account data:</strong> your name, email address and team membership, handled by
          our sign-in provider.
        </li>
        <li>
          <strong>Store catalogue and stock:</strong> products, variants, SKUs, costs, locations
          and inventory levels.
        </li>
        <li>
          <strong>Order line items:</strong> for each order we read only the products, quantities,
          prices and order date, and store them as daily totals per product and channel.
        </li>
        <li>
          <strong>Data you enter:</strong> suppliers (name, email, lead times), bills of materials,
          purchase orders, promotions and planning settings.
        </li>
        <li>
          <strong>Usage data:</strong> pages visited and product events (for example &quot;first
          forecast viewed&quot;) to improve the product, and error reports.
        </li>
      </ul>

      <h2>What we do not collect</h2>
      <p>
        We do not read or store your customers&apos; personal information: no names, email
        addresses, phone numbers, shipping or billing addresses, or payment details. Our store
        connectors request order line items only. Because of this, Shopify customer data requests
        and customer redaction requests have no Stockcast data to return or erase; we acknowledge
        and log them.
      </p>

      <h2>Why we use it</h2>
      <ul>
        <li>To forecast demand, plan reorders and production, and draft purchase orders for you.</li>
        <li>To send emails you asked for (purchase orders to suppliers, sync alerts, digests).</li>
        <li>To operate, secure, support and improve the service.</li>
      </ul>
      <p>We do not sell your data and do not use it to train models for anyone else.</p>

      <h2>Service providers</h2>
      <p>We use these processors to run Stockcast, each under a data-processing agreement:</p>
      <ul>
        <li>Railway (application hosting and database, United States)</li>
        <li>Vercel (web hosting, global edge)</li>
        <li>Clerk (sign-in and team management)</li>
        <li>Resend (transactional email)</li>
        <li>Sentry (error monitoring) and PostHog (product analytics)</li>
        <li>Shopify Billing or Paddle (subscription billing; we never see card numbers)</li>
      </ul>

      <h2>Retention and deletion</h2>
      <ul>
        <li>
          When you uninstall the Shopify app we stop syncing and delete the access token at once.
          All data that came from that shop is erased when Shopify sends its shop-redaction request
          (48 hours after uninstall).
        </li>
        <li>
          You can disconnect any channel or ask us to delete your workspace at any time; we delete
          it within 30 days. Encrypted backups are kept for at most 30 days.
        </li>
      </ul>

      <h2>Security</h2>
      <p>
        Data is encrypted in transit (TLS) and channel credentials are encrypted at rest. Access is
        limited to your workspace members, every database query is scoped to your workspace, and
        sensitive changes are recorded in an audit log.
      </p>

      <h2>Your rights</h2>
      <p>
        Depending on where you live (for example under the GDPR or CCPA) you can ask to access,
        correct, export or delete your personal data, or object to its use. Email{" "}
        <a href={`mailto:${site.supportEmail}`}>{site.supportEmail}</a> and we will respond within
        30 days.
      </p>

      <h2>Changes</h2>
      <p>
        We will post any changes here and update the date above; material changes are also emailed
        to workspace owners.
      </p>

      <h2>Contact</h2>
      <p>
        {site.legalEntity} · <a href={`mailto:${site.supportEmail}`}>{site.supportEmail}</a>
      </p>
    </Doc>
  );
}
