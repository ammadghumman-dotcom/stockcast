"use client";

import { usePathname } from "next/navigation";
import { useState } from "react";

import { unwrap } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import { useApi, useOrg } from "@/lib/org";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/dialog";

const RATINGS = [1, 2, 3, 4, 5] as const;

/** "Send feedback" in the sidebar: goes straight to the team (beta program). */
export function FeedbackButton() {
  const api = useApi();
  const { role } = useOrg();
  const page = usePathname();
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [rating, setRating] = useState<number | null>(null);
  const send = useAction(
    async () => unwrap(await api.POST("/feedback", { body: { message, rating, page } })),
    {
      success: "Thanks, your feedback was sent to the team",
      onSuccess: () => {
        setOpen(false);
        setMessage("");
        setRating(null);
      },
    },
  );
  if (role === "viewer") return null;
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button className="rounded-md px-3 py-1.5 text-left text-sm text-muted-foreground hover:bg-muted hover:text-foreground" data-testid="feedback-open">
          Send feedback
        </button>
      </DialogTrigger>
      <DialogContent title="Send feedback" description="What's working, what's missing, or what got in your way. The people building Stockcast read every message.">
        <fieldset>
          <legend className="text-sm font-medium">How useful is Stockcast so far?</legend>
          <div className="mt-2 flex gap-2">
            {RATINGS.map((n) => (
              <button
                key={n}
                type="button"
                aria-pressed={rating === n}
                onClick={() => setRating(rating === n ? null : n)}
                className={`size-9 rounded-md border text-sm ${rating === n ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted"}`}
              >
                {n}
              </button>
            ))}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">1 = not useful, 5 = can&apos;t do without it</p>
        </fieldset>
        <label className="block text-sm font-medium">
          Your feedback
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            rows={5}
            maxLength={5000}
            className="mt-1 w-full rounded-md border bg-background px-3 py-2 text-sm"
            placeholder="The jar order came out too early because our supplier's lead time changed…"
            data-testid="feedback-message"
          />
        </label>
        <div className="flex justify-end">
          <Button onClick={() => send.mutate(undefined)} loading={send.isPending} disabled={message.trim().length < 3} data-testid="feedback-send">
            Send feedback
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
