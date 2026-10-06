"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { clerkEnabled } from "@/lib/auth";
import { useOrg } from "@/lib/org";
import { cn } from "@/lib/utils";

import { AccountControls } from "./account";
import { SampleDataBanner } from "@/components/onboarding-checklist";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/recommendations", label: "Recommendations" },
  { href: "/products", label: "Products" },
  { href: "/raw-materials", label: "Raw materials" },
  { href: "/purchase-orders", label: "Purchase orders" },
  { href: "/calendar", label: "Calendar" },
  { href: "/settings", label: "Settings" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const { orgId, role, mode } = useOrg();
  const nav = (
    <nav className="flex flex-col gap-1">
      {NAV.map((n) => {
        const active = path === n.href || path.startsWith(n.href + "/");
        return (
          <Link
            key={n.href}
            href={n.href}
            onClick={() => setOpen(false)}
            className={cn("rounded-md px-3 py-2 text-sm", active ? "bg-primary text-primary-foreground" : "hover:bg-muted")}
          >
            {n.label}
          </Link>
        );
      })}
    </nav>
  );
  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-56 shrink-0 border-r p-4 md:block">
        <Link href="/dashboard" className="mb-6 block text-lg font-semibold tracking-tight">
          Stockcast
        </Link>
        {nav}
        {clerkEnabled ? <div className="mt-6 border-t pt-4"><AccountControls /></div> : null}
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b px-4 py-3 md:hidden">
          <button aria-label="Menu" className="rounded-md border px-2 py-1 text-sm" onClick={() => setOpen((o) => !o)}>
            ☰
          </button>
          <Link href="/dashboard" className="font-semibold">Stockcast</Link>
        </header>
        {open ? (
          <div className="border-b p-3 md:hidden">
            {nav}
            {clerkEnabled ? <div className="mt-3 border-t pt-3"><AccountControls /></div> : null}
          </div>
        ) : null}
        {mode === "clerk" && !orgId ? (
          <div className="border-b bg-amber-50 px-4 py-2 text-sm text-amber-900" data-testid="no-org-banner">
            Create or select an organization to see its data.
          </div>
        ) : null}
        {role === "viewer" ? (
          <div className="border-b bg-muted px-4 py-1.5 text-xs text-muted-foreground" data-testid="viewer-banner">
            You have view-only access in this organization.
          </div>
        ) : null}
        {orgId ? <SampleDataBanner /> : null}
        <main className="min-w-0 flex-1 p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}

export function PageHeader({ title, sub, actions }: { title: string; sub?: string; actions?: React.ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {sub ? <p className="text-sm text-muted-foreground">{sub}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}
