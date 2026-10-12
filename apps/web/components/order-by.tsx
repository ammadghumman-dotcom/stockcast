import { orderByLabel } from "@/lib/utils";

/** Order-by date; overdue ones read "Now · 2d late" in red instead of a past date. */
export function OrderBy({ d }: { d: string | null | undefined }) {
  const { text, overdue } = orderByLabel(d);
  return <span className={overdue ? "font-medium text-red-600" : undefined} data-testid="order-by">{text}</span>;
}
