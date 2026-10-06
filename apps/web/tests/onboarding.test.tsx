import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ChecklistView, nextStep, type OnboardingState } from "@/components/onboarding-checklist";

afterEach(cleanup);

const state = (done: boolean[]): OnboardingState => {
  const keys = ["connect", "bom", "suppliers", "forecast", "po"];
  const steps = keys.map((k, i) => ({ key: k, title: `Step ${k}`, hint: `hint ${k}`, href: `/${k}`, done: done[i] }));
  const n = done.filter(Boolean).length;
  return { steps, done: n, total: keys.length, complete: n === keys.length, sample_data: false };
};

describe("onboarding checklist", () => {
  it("suggests the first unfinished step", () => {
    expect(nextStep(state([true, false, false, true, false]).steps)?.key).toBe("bom");
    expect(nextStep(state([true, true, true, true, true]).steps)).toBeUndefined();
  });

  it("shows progress, links open steps and strikes done ones", () => {
    render(<ChecklistView state={state([true, false, true, false, false])} />);
    expect(screen.getByTestId("onboarding-progress").textContent).toBe("2 of 5 done");
    expect(screen.getByTestId("step-connect").getAttribute("data-done")).toBe("true");
    const bom = screen.getByRole("link", { name: "Step bom" });
    expect(bom.getAttribute("href")).toBe("/bom");
    expect(screen.queryByRole("link", { name: "Step connect" })).toBeNull();
  });

  it("disappears when everything is done", () => {
    const { container } = render(<ChecklistView state={state([true, true, true, true, true])} />);
    expect(container.innerHTML).toBe("");
  });
});
