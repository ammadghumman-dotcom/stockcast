import { describe, expect, it } from "vitest";

import { canEdit, memberActions } from "../lib/team";

const owner = { role: "owner", status: "active", email: "o@x.com" };
const admin = { role: "admin", status: "active", email: "a@x.com" };
const invited = { role: "viewer", status: "invited", email: "i@x.com" };

describe("memberActions", () => {
  it("never offers to remove the owner or change their role", () => {
    for (const me of ["owner", "admin"] as const) {
      const a = memberActions(me, "a@x.com", owner);
      expect(a.canRemove).toBe(false);
      expect(a.canChangeRole).toBe(false);
    }
  });

  it("only the owner can hand over ownership, and only to someone who signed in", () => {
    expect(
      memberActions("admin", "a@x.com", { ...admin, email: "b@x.com" })
        .canMakeOwner,
    ).toBe(false);
    expect(memberActions("owner", "o@x.com", admin).canMakeOwner).toBe(true);
    expect(memberActions("owner", "o@x.com", invited).canMakeOwner).toBe(false);
  });

  it("viewers and unknown roles get no controls; nobody removes themselves", () => {
    for (const me of ["viewer", null] as const) {
      const a = memberActions(me, null, invited);
      expect(a.canRemove || a.canChangeRole || a.canMakeOwner).toBe(false);
    }
    expect(memberActions("admin", "a@x.com", admin).canRemove).toBe(false);
    expect(memberActions("owner", "o@x.com", invited).canRemove).toBe(true);
  });

  it("canEdit is false while the role is loading", () => {
    expect(canEdit(null)).toBe(false);
    expect(canEdit("viewer")).toBe(false);
    expect(canEdit("admin")).toBe(true);
  });
});
