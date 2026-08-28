import { NextRequest, NextResponse } from "next/server";
import { backendUrl } from "@/lib/backend";
import { setSessionToken } from "@/lib/session";

// A visitor with no session cookie is redirected here by middleware.ts
// (which does zero I/O itself -- see that file for why). This route mints
// a guest session by calling the backend, sets the cookie, and bounces
// back to wherever the visitor was actually headed. It runs as a normal
// Node.js serverless function, not Edge Middleware, so it has a much
// larger execution budget and a slow/cold backend here just delays this
// one redirect instead of risking a 504 MIDDLEWARE_INVOCATION_TIMEOUT on
// every single request site-wide.
export const maxDuration = 15;

// Bounded well under maxDuration -- a fully-cold or dead backend still
// shouldn't be able to hang a visitor's very first page load for the
// whole function budget. Failing open (redirecting on without a cookie)
// after this window is strictly better than blocking; every downstream
// proxy route already 401s cleanly on a missing token, and apiFetch's
// existing redirect-on-401 handles the client side from there.
const GUEST_MINT_TIMEOUT_MS = 8000;

export async function GET(request: NextRequest): Promise<NextResponse> {
  const next = request.nextUrl.searchParams.get("next") || "/";
  const destination = new URL(next, request.url);

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), GUEST_MINT_TIMEOUT_MS);
    try {
      const guestResponse = await fetch(backendUrl("/api/v1/auth/guest"), {
        method: "POST",
        signal: controller.signal,
      });
      if (guestResponse.ok) {
        const body = (await guestResponse.json()) as { access_token: string };
        setSessionToken(body.access_token);
      }
    } finally {
      clearTimeout(timeout);
    }
  } catch {
    // Backend unreachable, slow, or timed out -- fall through and redirect
    // without a cookie, same fail-open contract the old in-middleware
    // version had.
  }

  return NextResponse.redirect(destination);
}
