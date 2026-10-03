import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium", {
  variants: {
    variant: {
      default: "border-transparent bg-primary text-primary-foreground",
      secondary: "border-transparent bg-muted text-foreground",
      success: "border-transparent bg-emerald-600 text-white",
      warning: "border-transparent bg-amber-500 text-white",
      destructive: "border-transparent bg-red-600 text-white",
      info: "border-transparent bg-sky-600 text-white",
      outline: "text-foreground",
    },
  },
  defaultVariants: { variant: "default" },
});

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

const HEALTH: Record<string, { label: string; variant: BadgeProps["variant"] }> = {
  healthy: { label: "Healthy", variant: "success" },
  at_risk: { label: "At risk", variant: "warning" },
  stockout: { label: "Stockout", variant: "destructive" },
  overstock: { label: "Overstock", variant: "info" },
};

export function HealthBadge({ health }: { health: string | null | undefined }) {
  const h = HEALTH[health ?? ""] ?? { label: health ?? "–", variant: "outline" as const };
  return <Badge variant={h.variant} data-testid={`health-${health}`}>{h.label}</Badge>;
}

export function ActionBadge({ action }: { action: string | null | undefined }) {
  if (!action || action === "none") return <Badge variant="outline">No action</Badge>;
  return <Badge variant={action === "produce" ? "info" : "default"}>{action === "produce" ? "Produce" : "Reorder"}</Badge>;
}

export function StatusBadge({ status }: { status: string }) {
  const v: BadgeProps["variant"] = status === "received" ? "success" : status === "sent" ? "info" : status === "failed" ? "destructive" : "secondary";
  return <Badge variant={v}>{status}</Badge>;
}
