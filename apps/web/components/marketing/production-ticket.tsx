/**
 * Hero illustration: one finished product's forecast, split by channel, exploded through its
 * bill of materials into component orders. Static example data, shaped like the real
 * recommendations (forecast p50 x qty_per_unit, lead times, order-by dates).
 */

const channels = [
  { name: "Shopify", units: 333, color: "#1f6f5c" },
  { name: "Amazon", units: 211, color: "#4f8f7f" },
  { name: "eBay", units: 96, color: "#9cc3b8" },
];
const total = channels.reduce((s, c) => s + c.units, 0);

type Line = {
  component: string;
  perUnit: string;
  need: string;
  onHand: string;
  action: { kind: "order" | "ok"; text: string; detail?: string };
};

const lines: Line[] = [
  {
    component: "Soy wax",
    perUnit: "227 g",
    need: "145 kg",
    onHand: "60 kg",
    action: { kind: "order", text: "Order 100 kg by Oct 14", detail: "10-day lead time" },
  },
  {
    component: "Amber jar, 8 oz",
    perUnit: "1",
    need: "640",
    onHand: "210",
    action: { kind: "order", text: "Order 500 by Oct 9", detail: "21-day lead time" },
  },
  {
    component: "Cotton wick",
    perUnit: "1",
    need: "640",
    onHand: "1,200",
    action: { kind: "ok", text: "Covered until Dec" },
  },
];

export function ProductionTicket() {
  return (
    <figure
      className="rounded-xl border border-[var(--mk-line)] bg-white shadow-[0_1px_0_var(--mk-line),0_24px_48px_-24px_rgba(27,42,58,0.35)]"
      aria-label="Example: a candle's 30-day forecast turned into raw-material orders"
    >
      <div className="border-b border-[var(--mk-line)] px-5 py-4">
        <p className="text-sm text-[var(--mk-ink-soft)]">Next 30 days</p>
        <div className="mt-1 flex items-baseline justify-between gap-4">
          <h3 className="mk-display text-lg font-semibold">Lavender soy candle, 8 oz</h3>
          <p className="mk-display text-2xl font-semibold">
            {total} <span className="text-sm font-normal text-[var(--mk-ink-soft)]">units</span>
          </p>
        </div>
        <div className="mt-3 flex h-2.5 overflow-hidden rounded-full" role="img" aria-label="Demand by channel">
          {channels.map((c) => (
            <span key={c.name} style={{ width: `${(c.units / total) * 100}%`, background: c.color }} />
          ))}
        </div>
        <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--mk-ink-soft)]">
          {channels.map((c) => (
            <li key={c.name} className="flex items-center gap-1.5">
              <span className="inline-block size-2 rounded-full" style={{ background: c.color }} />
              {c.name} {c.units}
            </li>
          ))}
          <li className="text-[var(--mk-ink)]">includes Diwali uplift ×1.4</li>
        </ul>
      </div>

      <svg viewBox="0 0 100 14" preserveAspectRatio="none" className="block h-4 w-full" aria-hidden>
        <path className="mk-flow" d="M50 0 V14" stroke="var(--mk-line)" strokeWidth="0.6" fill="none" />
      </svg>

      <table className="w-full text-sm">
        <caption className="sr-only">Components needed for the forecast</caption>
        <thead>
          <tr className="text-left text-xs text-[var(--mk-ink-soft)]">
            <th scope="col" className="px-5 pb-2 font-medium">
              Component
            </th>
            <th scope="col" className="px-2 pb-2 text-right font-medium">
              Needed
            </th>
            <th scope="col" className="px-2 pb-2 text-right font-medium">
              In stock
            </th>
            <th scope="col" className="hidden pb-2 pl-3 pr-5 font-medium sm:table-cell">
              Plan
            </th>
          </tr>
        </thead>
        <tbody>
          {lines.map((l) => (
            <tr key={l.component} className="border-t border-[var(--mk-line)] align-top">
              <td className="px-5 py-3">
                <span className="font-medium">{l.component}</span>
                <span className="block text-xs text-[var(--mk-ink-soft)]">{l.perUnit} per candle</span>
                <ActionChip action={l.action} className="mt-2 sm:hidden" />
              </td>
              <td className="px-2 py-3 text-right">{l.need}</td>
              <td className="px-2 py-3 text-right">{l.onHand}</td>
              <td className="hidden py-3 pl-3 pr-5 sm:table-cell">
                <ActionChip action={l.action} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}

function ActionChip({ action, className = "" }: { action: Line["action"]; className?: string }) {
  if (action.kind === "ok") {
    return <span className={`block text-[var(--mk-pine)] ${className}`}>{action.text}</span>;
  }
  return (
    <span className={`block ${className}`}>
      <span className="inline-block rounded bg-[var(--mk-wax)] px-1.5 py-0.5 font-medium text-[var(--mk-ink)]">
        {action.text}
      </span>
      {action.detail && <span className="mt-1 block text-xs text-[var(--mk-ink-soft)]">{action.detail}</span>}
    </span>
  );
}
