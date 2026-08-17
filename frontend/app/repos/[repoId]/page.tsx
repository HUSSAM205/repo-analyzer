import { notFound } from "next/navigation";
import { backendUrl } from "@/lib/backend";
import { getSessionToken } from "@/lib/session";
import { RepoHeader } from "@/components/workspace/repo-header";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import type { Repo } from "@/lib/types";

async function fetchRepo(repoId: string): Promise<Repo | null> {
  const token = getSessionToken();
  if (!token) return null;
  const res = await fetch(backendUrl("/api/v1/repos"), {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) return null;
  const repos = (await res.json()) as Repo[];
  return repos.find((r) => r.id === repoId) ?? null;
}

export default async function RepoWorkspacePage({
  params,
  searchParams,
}: {
  params: { repoId: string };
  searchParams: { job?: string };
}) {
  const repo = await fetchRepo(params.repoId);
  if (!repo) notFound();

  return (
    <>
      <RepoHeader repo={repo} jobId={searchParams.job} />
      <WorkspaceShell
        left={<div className="p-4 text-sm text-muted-foreground">File tree (Task 6)</div>}
        center={<div className="p-4 text-sm text-muted-foreground">Code viewer (Task 7)</div>}
        right={<div className="p-4 text-sm text-muted-foreground">Chat (Tasks 8-9)</div>}
      />
    </>
  );
}
