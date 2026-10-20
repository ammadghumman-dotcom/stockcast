"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { PADDLE_JS, paddleEnv, successUrl, transactionId } from "@/lib/paddle";

type PaddleGlobal = {
  Environment: { set: (env: string) => void };
  Initialize: (opts: { token: string; checkout?: { settings: { successUrl: string } } }) => void;
};

declare global {
  interface Window {
    Paddle?: PaddleGlobal;
  }
}

/** Paddle's default payment link points here: loading Paddle.js with `_ptxn` in the URL
 * opens the checkout for that transaction (created by POST /billing/checkout). */
export default function PaddlePayPage() {
  const [state, setState] = useState<"loading" | "open" | "invalid" | "unconfigured">("loading");

  useEffect(() => {
    const token = process.env.NEXT_PUBLIC_PADDLE_CLIENT_TOKEN;
    const txn = transactionId(new URLSearchParams(window.location.search));
    if (!txn) return setState("invalid");
    if (!token) return setState("unconfigured");
    const init = () => {
      const p = window.Paddle;
      if (!p) return;
      if (paddleEnv(process.env.NEXT_PUBLIC_PADDLE_ENV) === "sandbox") p.Environment.set("sandbox");
      p.Initialize({ token, checkout: { settings: { successUrl: successUrl(window.location.origin) } } });
      setState("open");
    };
    if (window.Paddle) return init();
    const s = document.createElement("script");
    s.src = PADDLE_JS;
    s.async = true;
    s.onload = init;
    document.head.appendChild(s);
  }, []);

  return (
    <main className="mx-auto max-w-md p-8 text-center" data-testid="paddle-pay">
      <h1 className="text-lg font-semibold">Stockcast checkout</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        {state === "loading" && "Opening secure checkout…"}
        {state === "open" && "Complete payment in the checkout window. Payments are processed by Paddle."}
        {state === "invalid" && "This checkout link is not valid. Start again from Settings → Billing."}
        {state === "unconfigured" && "Checkout is not available right now. Please try again later."}
      </p>
      <Link href="/settings" className="mt-4 inline-block text-sm underline">Back to Stockcast</Link>
    </main>
  );
}
