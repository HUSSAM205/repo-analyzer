import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { backendUrl } from "@/lib/backend";
import { getSessionToken } from "@/lib/session";
import { SubmitRepoForm } from "@/components/submit-repo-form";
import { RepoList } from "@/components/repo-list";
import type { Repo } from "@/lib/types";

async function fetchRepos(): Promise<Repo[]> {
  const token = getSessionToken();
  if (!token) redirect("/login");
  const res = await fetch(backendUrl("/api/v1/repos"), {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (res.status === 401) redirect("/login");
  if (!res.ok) return [];
  return res.json();
}

export default async function ReposPage() {
  cookies(); // opts this route into dynamic rendering (reads the session cookie)
  const repos = await fetchRepos();

  return (
    <main className="mx-auto max-w-2xl px-6 py-16">
      <h1 className="mb-6 text-2xl font-semibold">Your repositories</h1>
      <div className="mb-8">
        <SubmitRepoForm />
      </div>
      <RepoList repos={repos} />
    </main>
  );
}
