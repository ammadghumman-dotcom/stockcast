/**
 * Auth mode switch. With NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY set the app runs behind Clerk
 * (sign-in, organizations, roles) and sends the session JWT to the API. Without it, the
 * dev/e2e header mode from Step 6 stays: org id in a cookie, `X-Org-Id` on every request.
 */
export const CLERK_PUBLISHABLE_KEY = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY ?? "";
export const clerkEnabled = CLERK_PUBLISHABLE_KEY.length > 0;
