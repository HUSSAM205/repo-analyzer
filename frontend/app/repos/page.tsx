import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { backendUrl } from "@/lib/backend";
import { getSessionToken } from "@/lib/session";
import { RepoList } from "@/components/repo-list";
import type { Repo } from "@/lib/types";

async function fetchRepos(): Promise<Repo[]> {
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
  const res = await fetch(backendUrl("/api/v1/repos"), {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (res.status === 401) redirect("/api/auth/reset");
  if (!res.ok) return [];
  return res.json();
}

export default async function ReposPage() {
  cookies(); // opts this route into dynamic rendering (reads the session cookie)
  const repos = await fetchRepos();

  return (
    <main className="mx-auto max-w-2xl px-6 py-16">
      <h1 className="mb-6 text-2xl font-semibold">Your repositories</h1>
      <RepoList repos={repos} />
    </main>
  );
}
