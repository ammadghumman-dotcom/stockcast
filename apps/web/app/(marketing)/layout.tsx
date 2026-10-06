import "@fontsource-variable/bricolage-grotesque";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "./marketing.css";

import { SiteFooter, SiteHeader } from "@/components/marketing/chrome";

export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="mk flex min-h-screen flex-col">
      <SiteHeader />
      <main className="flex-1">{children}</main>
      <SiteFooter />
    </div>
  );
}
