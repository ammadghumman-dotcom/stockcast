/** Public-site settings. Everything brand/contact related is env-driven so the launch domain,
 * support inbox and legal entity can change without a code edit (set them in Vercel). */
export const site = {
  name: "Stockcast",
  url: (process.env.NEXT_PUBLIC_SITE_URL ?? "https://stockcast-web-phi.vercel.app").replace(/\/$/, ""),
  supportEmail: process.env.NEXT_PUBLIC_SUPPORT_EMAIL ?? "support@stockcast.app",
  legalEntity: process.env.NEXT_PUBLIC_LEGAL_ENTITY ?? "Stockcast",
  /** YouTube/Loom/Vimeo *embed* URL; the demo section hides itself when unset. */
  demoVideoUrl: process.env.NEXT_PUBLIC_DEMO_VIDEO_URL ?? "",
  legalUpdated: "October 6, 2026",
  tagline: "Demand forecasting and raw-material planning for multichannel brands",
} as const;
