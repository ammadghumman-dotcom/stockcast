import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const post = vi.fn(async () => ({ data: { id: "f1" }, error: undefined, response: new Response(null, { status: 201 }) }));
vi.mock("@/lib/org", () => ({ useApi: () => ({ POST: post }), useOrg: () => ({ role: "owner" }) }));
vi.mock("next/navigation", () => ({ usePathname: () => "/recommendations" }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/hooks", async () => {
  const { useState } = await import("react");
  return {
    useAction: (fn: () => Promise<unknown>, opts: { onSuccess?: () => void }) => {
      const [isPending, setPending] = useState(false);
      return {
        isPending,
        mutate: async () => {
          setPending(true);
          await fn();
          setPending(false);
          opts.onSuccess?.();
        },
      };
    },
  };
});

import { FeedbackButton } from "@/components/feedback";

afterEach(cleanup);

describe("feedback dialog", () => {
  it("sends message, rating and page", async () => {
    render(<FeedbackButton />);
    fireEvent.click(screen.getByTestId("feedback-open"));
    const send = screen.getByTestId("feedback-send");
    expect(send.hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "4" }));
    fireEvent.change(screen.getByTestId("feedback-message"), { target: { value: "Love the jar plan" } });
    fireEvent.click(send);
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post).toHaveBeenCalledWith("/feedback", {
      body: { message: "Love the jar plan", rating: 4, page: "/recommendations" },
    });
  });
});
