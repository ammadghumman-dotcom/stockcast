import Link from "next/link";

import { site } from "@/lib/site";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-30 border-b border-[var(--mk-line)] bg-white/90 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
        <Link href="/" className="mk-display text-xl font-semibold" data-testid="site-logo">
          {site.name}
        </Link>
        <nav className="flex items-center gap-4 text-sm sm:gap-6" aria-label="Main">
          <Link href="/#how" className="hidden text-[var(--mk-ink-soft)] hover:text-[var(--mk-ink)] sm:inline">
            How it works
          </Link>
          <Link href="/#pricing" className="text-[var(--mk-ink-soft)] hover:text-[var(--mk-ink)]">
            Pricing
          </Link>
          <Link href="/sign-in" className="text-[var(--mk-ink-soft)] hover:text-[var(--mk-ink)]">
            Sign in
          </Link>
          <Link
            href="/sign-up"
            className="rounded-md bg-[var(--mk-pine)] px-3.5 py-2 font-medium text-white hover:bg-[var(--mk-pine-dark)]"
          >
            Start free trial
          </Link>
        </nav>
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="border-t border-[var(--mk-line)]">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-10 text-sm text-[var(--mk-ink-soft)] sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <p>
          © {new Date().getFullYear()} {site.legalEntity}
        </p>
        <nav className="flex flex-wrap gap-x-5 gap-y-2" aria-label="Footer">
          <Link href="/privacy" className="hover:text-[var(--mk-ink)]">
            Privacy
          </Link>
          <Link href="/terms" className="hover:text-[var(--mk-ink)]">
            Terms
          </Link>
          <Link href="/support" className="hover:text-[var(--mk-ink)]">
            Support
          </Link>
          <a href={`mailto:${site.supportEmail}`} className="hover:text-[var(--mk-ink)]">
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
    <article className="mx-auto max-w-[68ch] px-4 py-14 text-[16px] leading-[1.7] sm:px-6 [&_a]:text-[var(--mk-pine)] [&_a]:underline [&_h2]:mb-2 [&_h2]:mt-10 [&_h2]:text-2xl [&_h2]:font-semibold [&_li]:ml-5 [&_li]:list-disc [&_li]:my-1.5 [&_p]:my-3 [&_ul]:my-3">
      <h1 className="mk-display text-4xl font-semibold">{title}</h1>
      <p className="mt-2 text-sm text-[var(--mk-ink-soft)]">Last updated {site.legalUpdated}</p>
      {children}
    </article>
  );
}
