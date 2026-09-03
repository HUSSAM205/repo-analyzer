import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { AlertTriangle } from "lucide-react";
import { backendUrl } from "@/lib/backend";
import { getSessionToken } from "@/lib/session";
import { Hero } from "@/components/hero";
import { RepoList } from "@/components/repo-list";
import { RepoListClient } from "@/components/repo-list-client";
import { FaqSection } from "@/components/faq-section";
import { SiteFooter } from "@/components/site-footer";
import type { Repo } from "@/lib/types";

type FetchReposResult = { ok: true; repos: Repo[] } | { ok: false } | { ok: "no-session" };

async function fetchRepos(): Promise<FetchReposResult> {
  const token = getSessionToken();
  // No session cookie yet is no longer an error path here: middleware.ts
  // now lets "/repos" render without one (see that file), so this page's
  // own shell (Hero/FAQ/footer, below) paints immediately and
  // <RepoListClient> takes over bootstrapping the guest session +
  // fetching the repo list client-side, instead of this Server Component
  // blocking on a redirect. A *stale/invalid* cookie is a different case,
  // still handled below via the 401 branch.
  if (!token) return { ok: "no-session" };

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
    <main className="mx-auto max-w-6xl px-6 py-10 sm:py-16">
      <Hero />
      <h2 className="mb-6 text-xl font-semibold text-foreground">Your repositories</h2>
      {result.ok === "no-session" ? (
        <RepoListClient />
      ) : result.ok ? (
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
      <FaqSection />
      <SiteFooter />
    </main>
  );
}
