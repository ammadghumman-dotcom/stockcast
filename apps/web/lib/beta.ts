/** Staff Beta page helpers (pure, unit-tested). */

export type WaitlistLike = { email: string; beta_fit: boolean; invited_at: string | null };

/** Pre-select the people worth inviting: fits the beta and not invited yet. */
export function defaultSelection(rows: WaitlistLike[]): Set<string> {
  return new Set(rows.filter((r) => r.beta_fit && !r.invited_at).map((r) => r.email));
}

export type InviteResult = { sent: string[]; skipped: string[]; failed: string[]; unknown: string[] };

export function inviteSummary(r: InviteResult): { text: string; ok: boolean } {
  const parts: string[] = [];
  if (r.sent.length) parts.push(`${r.sent.length} invite${r.sent.length === 1 ? "" : "s"} sent`);
  if (r.skipped.length) parts.push(`${r.skipped.length} already invited (not re-sent)`);
  if (r.failed.length) parts.push(`${r.failed.length} failed: ${r.failed.join(", ")}`);
  if (r.unknown.length) parts.push(`${r.unknown.length} not on the waitlist`);
  return { text: parts.join(" · ") || "Nothing to send", ok: r.failed.length === 0 };
}

export function stars(rating: number | null | undefined): string {
  return rating ? "★".repeat(rating) + "☆".repeat(5 - rating) : "–";
}
