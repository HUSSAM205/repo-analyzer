import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RepoHeader } from "./repo-header";
import type { Repo } from "@/lib/types";

const repo: Repo = { id: "r1", url: "https://github.com/octocat/Hello-World", name: "Hello-World", status: "ready", created_at: "" };

describe("RepoHeader", () => {
  it("renders the repo name and a ready status dot", () => {
    render(<RepoHeader repo={repo} job={null} polling={false} />);
    expect(screen.getByText("Hello-World")).toBeInTheDocument();
  });

  it("has no sign-out control", () => {
    render(<RepoHeader repo={repo} job={null} polling={false} />);
    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
  });

  it("shows a 'lost connection' message instead of the pulsing 'Analyzing...' text when pollingFailed", () => {
    const job = { id: "j1", repo_id: "r1", status: "running" as const, progress: 47, error_message: null, skipped_files: 0, started_at: null, finished_at: null };
    render(<RepoHeader repo={repo} job={job} polling={false} pollingFailed />);

    expect(screen.getByText(/lost connection to analysis job/i)).toBeInTheDocument();
    expect(screen.queryByText(/Analyzing\.\.\. 47%/)).not.toBeInTheDocument();
  });

  it("falls back to repo.latest_job's error message when there's no polled job (reload without ?job=)", () => {
    const failedRepo: Repo = {
      ...repo,
      status: "failed",
      latest_job: {
        id: "j1",
        repo_id: "r1",
        status: "failed",
        progress: 30,
        error_message: "Clone failed: repository not found",
        skipped_files: 0,
        started_at: null,
        finished_at: null,
      },
    };

    render(<RepoHeader repo={failedRepo} job={null} polling={false} />);

    expect(screen.getByText("Clone failed: repository not found")).toBeInTheDocument();
  });

  it("falls back to repo.status/no message when repo.latest_job is absent (older backend response)", () => {
    const failedRepo: Repo = { ...repo, status: "failed" };
    render(<RepoHeader repo={failedRepo} job={null} polling={false} />);

    expect(screen.getByText("Analysis failed")).toBeInTheDocument();
  });

  it("shows repo.latest_job's in-progress percentage when there's no polled job", () => {
    const runningRepo: Repo = {
      ...repo,
      status: "pending",
      latest_job: {
        id: "j1",
        repo_id: "r1",
        status: "running",
        progress: 62,
        error_message: null,
        skipped_files: 0,
        started_at: null,
        finished_at: null,
      },
    };

    render(<RepoHeader repo={runningRepo} job={null} polling={false} />);

    expect(screen.getByText("Analyzing... 62%")).toBeInTheDocument();
  });

  it("shows the Compare trigger once the repo is ready, and opens the compare modal on click", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => [] }) as unknown as typeof fetch;

    render(<RepoHeader repo={repo} job={null} polling={false} />);

    const trigger = screen.getByRole("button", { name: /compare/i });
    expect(trigger).toBeInTheDocument();

    await userEvent.click(trigger);

    expect(screen.getByRole("dialog", { name: /compare repositories/i })).toBeInTheDocument();
  });

  it("hides the Compare trigger while the repo is still analyzing", () => {
    const pendingRepo: Repo = { ...repo, status: "pending" };
    render(<RepoHeader repo={pendingRepo} job={null} polling={false} />);

    expect(screen.queryByRole("button", { name: /compare/i })).not.toBeInTheDocument();
  });
});
