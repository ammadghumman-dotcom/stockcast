/** Draft PO edits: typed quantities -> PATCH /purchase-orders/{id} body. */

export type EditableLine = { id: string; qty: string | number };

export function poEditBody(
  lines: EditableLine[],
  edits: Record<string, string>,
): { body: { lines: Record<string, string> } | null } | { error: string } {
  const out: Record<string, string> = {};
  for (const ln of lines) {
    const raw = edits[ln.id];
    if (raw === undefined || raw.trim() === "") continue;
    const n = Number(raw);
    if (!Number.isFinite(n) || n < 0) return { error: "Quantities must be 0 or more" };
    if (n !== Number(ln.qty)) out[ln.id] = String(n);
  }
  const remaining = lines.filter((ln) => Number(out[ln.id] ?? ln.qty) > 0).length;
  if (remaining === 0) return { error: "Keep at least one line on the PO" };
  return { body: Object.keys(out).length ? { lines: out } : null };
}
