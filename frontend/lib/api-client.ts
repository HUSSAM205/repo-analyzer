"use client";

export async function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(input, init);
  if (response.status === 401 && typeof window !== "undefined") {
    // No /login to send anyone to anymore -- "/" lets the middleware's
    // guest-mint have another go (same pattern as app/repos/page.tsx and
    // app/page.tsx use for a missing/invalid token).
    window.location.href = "/";
  }
  return response;
}
