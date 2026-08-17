import { NextRequest, NextResponse } from "next/server";
import { backendUrl } from "@/lib/backend";

const SESSION_COOKIE = "session_token";

// The sole place a visitor's session is created. Every prior version of
// this middleware protected /repos/* by redirecting unauthenticated
// visitors to /login; there is no login anymore -- instead, the first
// request from a browser with no session cookie silently mints one via
// the backend's guest endpoint (sub-project 3A) and sets it here, before
// any page renders. Every existing proxy route and apiFetch's
// redirect-on-401 logic (lib/api-client.ts) keeps working completely
// unchanged; they simply always find a valid token now.
//
// lib/session.ts's setSessionToken() can't be reused directly here --
// it's built on next/headers' cookies(), which only works inside Server
// Components and Route Handlers, not Edge Middleware. The cookie options
// below are intentionally identical to that function's.
export async function middleware(request: NextRequest): Promise<NextResponse> {
  const existing = request.cookies.get(SESSION_COOKIE)?.value;
  const response = NextResponse.next();
  if (existing) {
    return response;
  }

  try {
    const guestResponse = await fetch(backendUrl("/api/v1/auth/guest"), { method: "POST" });
    if (guestResponse.ok) {
      const body = (await guestResponse.json()) as { access_token: string };
      response.cookies.set(SESSION_COOKIE, body.access_token, {
        httpOnly: true,
        secure: process.env.NODE_ENV === "production",
        sameSite: "lax",
        path: "/",
        maxAge: 60 * 60,
      });
    }
  } catch {
    // Backend unreachable -- let the request through without a cookie.
    // Every downstream proxy route already 401s cleanly on a missing
    // token, and apiFetch's existing redirect-on-401 handles the client
    // side; this middleware never blocks navigation on backend health.
  }
  return response;
}

export const config = {
  // Every request except Next's own static asset paths -- pages and API
  // proxy routes alike need a session cookie to exist before they run.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
