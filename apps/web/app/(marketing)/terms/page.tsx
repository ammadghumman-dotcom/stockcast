import type { Metadata } from "next";

import { Doc } from "@/components/marketing/chrome";
import { site } from "@/lib/site";

export const metadata: Metadata = {
  title: "Terms of service · Stockcast",
  description: "The terms that apply when you use Stockcast.",
  alternates: { canonical: "/terms" },
};

export default function TermsPage() {
  return (
    <Doc title="Terms of service">
      <p>
        These terms are an agreement between you (or the company you represent) and{" "}
        {site.legalEntity} for the use of Stockcast. By creating a workspace or installing the app
        you accept them.
      </p>

      <h2>The service</h2>
      <p>
        Stockcast connects to your sales channels, forecasts demand and suggests reorder and
        production quantities. Forecasts and recommendations are estimates to support your
        decisions; you remain responsible for what you order, produce and sell.
      </p>

      <h2>Your account</h2>
      <ul>
        <li>Keep your sign-in secure and make sure your team members follow these terms.</li>
        <li>
          Only connect stores and accounts you are authorised to connect, and only upload data you
          have the right to use.
        </li>
        <li>Do not misuse the service, attempt to access other workspaces, or overload it.</li>
      </ul>

      <h2>Your data</h2>
      <p>
        You own your data. You give us permission to process it only to provide and improve the
        service, as described in our <a href="/privacy">privacy policy</a>. You can export your
        data as CSV and delete your workspace at any time.
      </p>

      <h2>Plans and billing</h2>
      <ul>
        <li>New workspaces start with a free trial. Paid plans renew monthly until cancelled.</li>
        <li>
          If you installed Stockcast from the Shopify App Store, charges appear on your Shopify
          bill; otherwise they are billed by our payment provider.
        </li>
        <li>
          You can cancel at any time; access continues until the end of the paid period. Fees
          already paid are not refunded except where required by law.
        </li>
        <li>We will give at least 30 days&apos; notice of any price change.</li>
      </ul>

      <h2>Availability and changes</h2>
      <p>
        We work to keep Stockcast available and secure but do not guarantee uninterrupted service.
        We may improve or change features; we will not remove core functionality you pay for
        without notice.
      </p>

      <h2>Liability</h2>
      <p>
        To the extent permitted by law, the service is provided &quot;as is&quot;, and our total
        liability for any claim is limited to the fees you paid in the 12 months before the claim.
        We are not liable for indirect losses such as lost profits or stock-outs.
      </p>

      <h2>Ending the agreement</h2>
      <p>
        You can stop using Stockcast at any time. We may suspend workspaces that break these terms.
        On termination we delete your data as described in the privacy policy.
      </p>

      <h2>Contact</h2>
      <p>
        Questions about these terms: <a href={`mailto:${site.supportEmail}`}>{site.supportEmail}</a>
      </p>
    </Doc>
  );
}
