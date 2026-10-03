"use client";

import { OrganizationSwitcher, UserButton } from "@clerk/nextjs";

/** Clerk org switcher + user menu (rendered only when Clerk is enabled). */
export function AccountControls() {
  return (
    <div className="flex flex-col gap-3">
      <OrganizationSwitcher
        hidePersonal
        afterCreateOrganizationUrl="/onboarding"
        afterSelectOrganizationUrl="/dashboard"
        appearance={{ elements: { rootBox: "w-full", organizationSwitcherTrigger: "w-full justify-between px-2 py-1.5 text-sm" } }}
      />
      <UserButton showName appearance={{ elements: { rootBox: "w-full", userButtonTrigger: "w-full justify-start px-2 py-1.5" } }} />
    </div>
  );
}
