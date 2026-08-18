"use client";

export async function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(input, init);
  if (response.status === 401 && typeof window !== "undefined") {
    // No /login to send anyone to anymore -- /api/auth/reset clears the
    // stale/invalid session cookie and then lets the middleware's
    // guest-mint have another go on "/" (same pattern as
    // app/repos/page.tsx uses for a missing/invalid token). Going straight
    // to "/" without clearing the cookie would risk a redirect loop: "/"
    // only checks cookie *presence*, so a present-but-backend-rejected
    // cookie would just bounce back to /repos, which 401s and comes right
    // back here.
    window.location.href = "/api/auth/reset";
  }
  return response;
}
