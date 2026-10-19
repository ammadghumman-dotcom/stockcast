/** Paddle.js settings for the default payment link page (/billing/pay). */

export const PADDLE_JS = "https://cdn.paddle.com/paddle/v2/paddle.js";

export type PaddleEnv = "sandbox" | "production";

export function paddleEnv(raw: string | undefined): PaddleEnv {
  return raw === "production" ? "production" : "sandbox";
}

/** Paddle appends `_ptxn=txn_…` to the default payment link; anything else is not a checkout. */
export function transactionId(params: URLSearchParams): string | null {
  const t = params.get("_ptxn");
  return t && /^txn_[a-z0-9]+$/i.test(t) ? t : null;
}

export function successUrl(origin: string): string {
  return `${origin}/settings?billing=success`;
}
