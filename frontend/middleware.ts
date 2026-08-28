import { NextRequest, NextResponse } from "next/server";

const SESSION_COOKIE = "session_token";

// Deliberately zero I/O. This used to `await fetch(...)` the backend
// directly here to mint a guest session on a visitor's first request --
// simple, but it meant EVERY request site-wide (this middleware runs on
// almost every path, see `matcher` below) was one blocking network call
// away from a hard 504 MIDDLEWARE_INVOCATION_TIMEOUT whenever the backend
// was slow (a cold Render instance, or any other backend-side latency --
// confirmed live as the actual cause of a production outage). Edge
// Middleware's execution budget is small and non-negotiable; it must stay
// synchronous/in-memory only.
//
// The real work (calling the backend, setting the cookie) now happens in
// app/api/auth/bootstrap/route.ts, a normal Node.js serverless function
// with a much larger budget. This middleware only ever checks whether a
// session cookie already exists and, if not, redirects there once --
// lib/session.ts's setSessionToken() (next/headers' cookies()) can't be
// called from Edge Middleware either way, only from a Server
// Component/Route Handler, which is the other reason this had to move.
export function middleware(request: NextRequest): NextResponse {
  if (request.cookies.has(SESSION_COOKIE)) {
    return NextResponse.next();
  }

  const bootstrapUrl = new URL("/api/auth/bootstrap", request.url);
  bootstrapUrl.searchParams.set("next", request.nextUrl.pathname + request.nextUrl.search);
  return NextResponse.redirect(bootstrapUrl);
}

export const config = {
  matcher: [
    // Every request except Next's own static assets, the bootstrap route
    // itself (it must run with no cookie present -- excluding it is what
    // stops this from redirecting to itself forever), and the two
    // deliberately-unauthenticated health/keepalive endpoints (a stateless
    // uptime pinger hitting those on a schedule would otherwise mint a
    // brand-new throwaway guest account on every single ping).
    "/((?!_next/static|_next/image|favicon.ico|api/auth/bootstrap|api/health|api/keepalive).*)",
  ],
};
