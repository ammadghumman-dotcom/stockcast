import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PrivacyPage from "@/app/(marketing)/privacy/page";
import SupportPage from "@/app/(marketing)/support/page";
import TermsPage from "@/app/(marketing)/terms/page";
import { site } from "@/lib/site";

describe("legal and support pages (Shopify review requirements)", () => {
  it("privacy states that customer personal data is not stored and how deletion works", () => {
    render(<PrivacyPage />);
    expect(screen.getByRole("heading", { name: "What we do not collect" })).toBeTruthy();
    expect(screen.getByText(/do not read or store your customers/i)).toBeTruthy();
    expect(screen.getByText(/48 hours after uninstall/i)).toBeTruthy();
  });

  it("every page links the support inbox", () => {
    for (const Page of [PrivacyPage, TermsPage, SupportPage]) {
      const { unmount } = render(<Page />);
      const links = screen
        .getAllByRole("link")
        .filter((a) => a.getAttribute("href") === `mailto:${site.supportEmail}`);
      expect(links.length).toBeGreaterThan(0);
      unmount();
    }
  });
});
