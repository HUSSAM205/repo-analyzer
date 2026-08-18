import { NextResponse } from "next/server";
import { clearSessionToken } from "@/lib/session";

// Clears a present-but-backend-invalid session cookie before landing back on
// "/". Without this step, "/" only checks whether a cookie is *present* (see
// app/page.tsx) -- so a stale/rejected cookie would just bounce straight
// back to "/repos", which would 401 and redirect to "/" again, forever. This
// route is the terminal step every "redirect to '/' because auth failed"
// path should go through instead of redirecting to "/" directly.
export async function GET(request: Request) {
  clearSessionToken();
  return NextResponse.redirect(new URL("/", request.url));
}
