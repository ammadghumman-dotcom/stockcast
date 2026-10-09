import type { Role } from "./org";

export type Member = { role: string; status?: string; email: string };

/** What the signed-in person may do to one team row. Mirrors the API rules in
 * services/team.py (the API enforces them; this only hides controls that would fail). */
export function memberActions(
  me: Role | null,
  myEmail: string | null,
  m: Member,
) {
  const manager = me === "owner" || me === "admin";
  const isOwnerRow = m.role === "owner";
  const isMe = !!myEmail && m.email.toLowerCase() === myEmail.toLowerCase();
  return {
    canRemove: manager && !isOwnerRow && !isMe,
    canChangeRole: manager && !isOwnerRow,
    canMakeOwner: me === "owner" && !isOwnerRow && m.status !== "invited",
  };
}

export const canEdit = (role: Role | null) =>
  role === "owner" || role === "admin";

export const INVITE_ROLES = [
  { value: "viewer", label: "Viewer" },
  { value: "admin", label: "Admin" },
] as const;
