import Link from "next/link";

import { site } from "@/lib/site";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-30 border-b bg-background/90 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
        <Link href="/" className="font-semibold tracking-tight" data-testid="site-logo">
          {site.name}
        </Link>
        <nav className="flex items-center gap-4 text-sm sm:gap-6">
          <Link href="/#how" className="hidden text-muted-foreground hover:text-foreground sm:inline">
            How it works
          </Link>
          <Link href="/#pricing" className="text-muted-foreground hover:text-foreground">
            Pricing
          </Link>
          <Link href="/sign-in" className="text-muted-foreground hover:text-foreground">
            Sign in
          </Link>
          <Link
            href="/sign-up"
            className="rounded-md bg-primary px-3 py-1.5 font-medium text-primary-foreground hover:opacity-90"
          >
            Start free
          </Link>
        </nav>
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="border-t">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-8 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <p>
          © {new Date().getFullYear()} {site.legalEntity}
        </p>
        <nav className="flex flex-wrap gap-x-5 gap-y-2">
          <Link href="/privacy" className="hover:text-foreground">
            Privacy
          </Link>
          <Link href="/terms" className="hover:text-foreground">
            Terms
          </Link>
          <Link href="/support" className="hover:text-foreground">
            Support
          </Link>
          <a href={`mailto:${site.supportEmail}`} className="hover:text-foreground">
            {site.supportEmail}
          </a>
        </nav>
      </div>
    </footer>
  );
}

/** Long-form legal/support text without pulling in a typography plugin. */
export function Doc({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <article className="mx-auto max-w-3xl px-4 py-12 text-[15px] leading-7 [&_a]:underline [&_h2]:mb-2 [&_h2]:mt-10 [&_h2]:text-xl [&_h2]:font-semibold [&_li]:ml-5 [&_li]:list-disc [&_p]:my-3 [&_ul]:my-3">
      <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
      <p className="text-sm text-muted-foreground">Last updated {site.legalUpdated}</p>
      {children}
    </article>
  );
}
