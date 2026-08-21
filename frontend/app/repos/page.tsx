import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { AlertTriangle } from "lucide-react";
import { backendUrl } from "@/lib/backend";
import { getSessionToken } from "@/lib/session";
import { Hero } from "@/components/hero";
import { RepoList } from "@/components/repo-list";
import type { Repo } from "@/lib/types";

type FetchReposResult = { ok: true; repos: Repo[] } | { ok: false };

async function fetchRepos(): Promise<FetchReposResult> {
  const token = getSessionToken();
  // No /login to send anyone to anymore. A missing/invalid token here
  // means the middleware's guest-mint attempt itself failed (backend
  // unreachable) -- redirect through /api/auth/reset (clears any stale
  // cookie, then lands on "/") so middleware gets a genuinely clean shot
  // at minting a fresh guest session on the next request, rather than
  // rendering a broken authenticated page, 404ing on a route that no
  // longer exists, or looping forever against a present-but-invalid
  // cookie (see /api/auth/reset/route.ts for why the cookie must be
  // cleared here rather than just redirecting straight to "/").
  if (!token) redirect("/api/auth/reset");

  // `redirect()` below works by throwing a special Next.js-internal error
  // that the framework catches further up to actually perform the
  // redirect -- so it must never sit inside this try/catch, or the catch
  // block would swallow that throw and turn an intended redirect into the
  // "can't reach the server" fallback instead. Only the fetch itself (a
  // genuine network failure -- backend down, DNS blip, etc.) is guarded.
  let res: Response;
  try {
    res = await fetch(backendUrl("/api/v1/repos"), {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
  } catch {
    // Backend unreachable. This is a Server Component render -- an
    // unguarded throw here crashes straight to Next's generic, unthemed
    // error screen with no way back into the app, since there's no
    // app/error.tsx anywhere in the project. Render an in-theme fallback
    // instead.
    return { ok: false };
  }

  if (res.status === 401) redirect("/api/auth/reset");
  if (!res.ok) return { ok: false };

  try {
    return { ok: true, repos: await res.json() };
  } catch {
    return { ok: false };
  }
}

export default async function ReposPage() {
  cookies(); // opts this route into dynamic rendering (reads the session cookie)
  const result = await fetchRepos();

  return (
    <main className="mx-auto max-w-5xl px-6 py-10 sm:py-16">
      <Hero />
      <h2 className="mb-6 text-xl font-semibold text-foreground">Your repositories</h2>
      {result.ok ? (
        <RepoList repos={result.repos} />
      ) : (
        <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-border p-8 text-center">
          <AlertTriangle className="h-6 w-6 text-destructive" aria-hidden="true" />
          <p className="text-sm font-medium text-zinc-100">Can&apos;t reach the server</p>
          <p className="text-sm text-muted-foreground">
            We couldn&apos;t load your repositories right now. The backend may be temporarily unavailable --
            please try refreshing the page in a moment.
          </p>
        </div>
      )}
    </main>
  );
}
