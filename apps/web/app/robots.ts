import type { MetadataRoute } from "next";

import { site } from "@/lib/site";

/** Index the public site only; the signed-in app is behind auth anyway. */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: ["/", "/privacy", "/terms", "/support"],
      disallow: ["/dashboard", "/products", "/onboarding", "/settings", "/shopify", "/sign-in", "/sign-up"],
    },
    sitemap: `${site.url}/sitemap.xml`,
  };
}
