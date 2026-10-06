import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";
import { NextResponse, type NextRequest } from "next/server";

import { clerkEnabled } from "@/lib/auth";
import { embeddedFrameAncestors } from "@/lib/shopify-embed";

// Marketing + legal pages must be reachable signed-out (Shopify app review checks them).
const isPublic = createRouteMatcher([
  "/",
  "/sign-in(.*)",
  "/sign-up(.*)",
  "/privacy",
  "/terms",
  "/support",
]);

const withClerk = clerkMiddleware(async (auth, req) => {
  if (!isPublic(req)) await auth.protect();
});

/** The embedded Shopify app authenticates with App Bridge session tokens, not Clerk, and may
 * only be framed by the shop's own admin (Shopify App Store requirement). */
function embedded(req: NextRequest) {
  const headers = new Headers(req.headers);
  headers.set("x-pathname", req.nextUrl.pathname);
  const res = NextResponse.next({ request: { headers } });
  res.headers.set(
    "Content-Security-Policy",
    `frame-ancestors ${embeddedFrameAncestors(req.nextUrl.searchParams.get("shop"))};`,
  );
  return res;
}

export default function middleware(req: NextRequest, ev: Parameters<typeof withClerk>[1]) {
  if (req.nextUrl.pathname === "/shopify" || req.nextUrl.pathname.startsWith("/shopify/")) {
    return embedded(req);
  }
  return clerkEnabled ? withClerk(req, ev) : NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next|.*\\..*).*)", "/(api|trpc)(.*)"],
};
