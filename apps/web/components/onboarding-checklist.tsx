"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { unwrap } from "@/lib/api";
import { useAction, useOrgQuery } from "@/lib/hooks";
import { useApi, useOrg } from "@/lib/org";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export type OnboardingStep = {
  key: string;
  title: string;
  hint: string;
  href: string;
  done: boolean;
};
export type OnboardingState = {
  steps: OnboardingStep[];
  done: number;
  total: number;
  complete: boolean;
  sample_data: boolean;
};

export function useOnboarding() {
  const api = useApi();
  return useOrgQuery(
    ["onboarding"],
    async () => unwrap(await api.GET("/onboarding")) as OnboardingState,
  );
}

/** The next step to suggest: the first one not done (steps come back in order). */
export function nextStep(steps: OnboardingStep[]): OnboardingStep | undefined {
  return steps.find((s) => !s.done);
}

/** Checklist card on the dashboard; renders nothing once every step is done. */
export function OnboardingChecklist() {
  const q = useOnboarding();
  return q.data ? <ChecklistView state={q.data} /> : null;
}

export function ChecklistView({ state }: { state: OnboardingState }) {
  if (state.complete) return null;
  const { steps, done, total } = state;
  const next = nextStep(steps);
  return (
    <Card className="mb-6" data-testid="onboarding-checklist">
      <CardHeader className="flex flex-row items-baseline justify-between gap-3">
        <CardTitle>Set up Stockcast</CardTitle>
        <span
          className="text-sm text-muted-foreground"
          data-testid="onboarding-progress"
        >
          {done} of {total} done
        </span>
      </CardHeader>
      <CardContent>
        <div
          className="mb-4 h-1.5 overflow-hidden rounded-full bg-muted"
          aria-hidden
        >
          <div
            className="h-full bg-primary transition-[width]"
            style={{ width: `${(100 * done) / total}%` }}
          />
        </div>
        <ol className="space-y-2">
          {steps.map((s) => (
            <li
              key={s.key}
              className="flex items-start gap-3"
              data-testid={`step-${s.key}`}
              data-done={s.done}
            >
              <span
                aria-hidden
                className={
                  s.done
                    ? "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-primary text-[11px] text-primary-foreground"
                    : "mt-0.5 size-5 shrink-0 rounded-full border-2"
                }
              >
                {s.done ? "✓" : null}
              </span>
              <div className="min-w-0">
                {s.done ? (
                  <span className="text-muted-foreground line-through">
                    {s.title}
                  </span>
                ) : (
                  <Link
                    href={s.href}
                    className={
                      s === next ? "font-medium underline" : "underline"
                    }
                  >
                    {s.title}
                  </Link>
                )}
                <span className="sr-only">
                  {s.done ? " (done)" : " (to do)"}
                </span>
                {!s.done ? (
                  <p className="text-xs text-muted-foreground">{s.hint}</p>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

/** Loads the demo brand, runs forecast + plan on it, then opens the dashboard. */
export function useLoadSampleData() {
  const api = useApi();
  const router = useRouter();
  return useAction(
    async () => {
      unwrap(await api.POST("/sample-data"));
      return unwrap(
        await api.POST("/forecast-runs", {
          params: { query: { horizon: 90, then_plan: true } },
        }),
      );
    },
    {
      success:
        "Sample data loaded. The forecast and plan are being built and appear in a few minutes.",
      invalidate: [],
      onSuccess: () => router.push("/dashboard"),
    },
  );
}

/** App-wide banner while sample data is in the workspace. */
export function SampleDataBanner() {
  const api = useApi();
  const { role } = useOrg();
  const q = useOnboarding();
  const remove = useAction(
    async () => unwrap(await api.DELETE("/sample-data")),
    {
      success: (r) => `Removed sample data (${r.removed_products} products)`,
      invalidate: [],
    },
  );
  if (!q.data?.sample_data) return null;
  return (
    <div
      className="flex flex-wrap items-center justify-between gap-2 border-b bg-sky-50 px-4 py-2 text-sm text-sky-950"
      data-testid="sample-banner"
    >
      <span>
        You&apos;re looking at sample data for a demo candle brand. Products and
        channels marked &ldquo;sample&rdquo; disappear when you remove it.
      </span>
      {role === "owner" || role === "admin" ? (
        <Button
          size="sm"
          variant="outline"
          loading={remove.isPending}
          onClick={() => remove.mutate(undefined)}
          data-testid="remove-sample"
        >
          Remove sample data
        </Button>
      ) : null}
    </div>
  );
}
