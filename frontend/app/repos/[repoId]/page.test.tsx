import type { ReactNode } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RepoWorkspacePage from "./page";

jest.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  notFound: jest.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
}));

// jest.mock's module specifier is resolved by Jest's own resolver, which (unlike
// regular `import` statements, which Next's SWC transform rewrites using the "@/*"
// tsconfig path alias at compile time) knows nothing about that alias — so these
// must use relative paths to the same files instead of "@/...".
jest.mock("../../../components/workspace/repo-header", () => ({
  RepoHeader: () => <div data-testid="repo-header" />,
}));

jest.mock("../../../components/workspace/workspace-shell", () => ({
  WorkspaceShell: ({ left, center, right }: { left: ReactNode; center: ReactNode; right: ReactNode }) => (
    <div data-testid="workspace-shell">
      {left}
      {center}
      {right}
    </div>
  ),
}));

jest.mock("../../../components/workspace/file-tree", () => ({
  FileTree: () => <div data-testid="file-tree" />,
}));

jest.mock("../../../components/workspace/code-viewer", () => ({
  CodeViewer: ({ path }: { path: string | null }) => <div data-testid="code-viewer">{path}</div>,
}));

// Unlike its siblings above, ChatPanel was previously left unmocked here.
// It runs its own real fetch to `/api/repos/{id}/conversations` and its own
// setInterval-driven effects, which is harmless while `repo` fetch fails or
// notFound() fires early -- but once the repo-detail fetch actually
// succeeds and the shell renders, that live component keeps state updates
// in flight past this test's own assertions, and those updates racing into
// a later test's render (e.g. the notFound() test, which intentionally
// throws) surface as a flaky uncaught exception attributed to whichever
// test happens to be running when they land. Mocking it the same way as
// the other workspace children removes that cross-test timing hazard.
jest.mock("../../../components/workspace/chat-panel", () => ({
  ChatPanel: ({ onCitationClick }: { onCitationClick?: (path: string) => void }) => (
    <div data-testid="chat-panel">
      <button type="button" onClick={() => onCitationClick?.("app/core/agent.py")}>
        cite
      </button>
    </div>
  ),
}));

describe("RepoWorkspacePage error handling", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("shows a distinct error message (not a 404) when the repos fetch rejects outright", async () => {
    // Simulates the backend being down / a network failure. Before the fix this left
    // `repo` stuck at `undefined` forever (infinite "Loading...") with an unhandled
    // promise rejection, since the effect had no .catch.
    global.fetch = jest.fn().mockRejectedValue(new TypeError("Failed to fetch")) as unknown as typeof fetch;

    render(<RepoWorkspacePage params={{ repoId: "some-repo-id" }} />);

    await waitFor(() => {
      expect(screen.getByText("Could not load this repository.")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("workspace-shell")).not.toBeInTheDocument();
  });

  it("shows the same error message (not notFound) when the repos endpoint returns a non-ok status", async () => {
    // Simulates a backend 500. Before the fix this mapped to `[]`, so the repo was
    // never found in the (empty) list and the page called notFound() — presenting a
    // server error to the user as "this repo doesn't exist".
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ detail: "Internal Server Error" }),
    }) as unknown as typeof fetch;

    render(<RepoWorkspacePage params={{ repoId: "some-repo-id" }} />);

    await waitFor(() => {
      expect(screen.getByText("Could not load this repository.")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("workspace-shell")).not.toBeInTheDocument();
  });

  it("renders the workspace shell when the repo is found", async () => {
    const repo = { id: "some-repo-id", url: "https://github.com/a/b", name: "b", status: "ready", created_at: "" };
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => repo,
    }) as unknown as typeof fetch;

    render(<RepoWorkspacePage params={{ repoId: "some-repo-id" }} />);

    await waitFor(() => {
      expect(screen.getByTestId("workspace-shell")).toBeInTheDocument();
    });

    expect(screen.getByTestId("repo-header")).toBeInTheDocument();
    expect(screen.queryByText("Could not load this repository.")).not.toBeInTheDocument();
  });

  it("calls notFound() when the repo endpoint returns 404", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: "Repo not found" }),
    }) as unknown as typeof fetch;

    render(<RepoWorkspacePage params={{ repoId: "some-repo-id" }} />);

    await waitFor(() => {
      expect(screen.queryByTestId("workspace-shell")).not.toBeInTheDocument();
    });
  });

  it("shows the staged AnalysisProgress (via repo.latest_job.stage) instead of the briefing while the repo is still analyzing", async () => {
    const repo = {
      id: "some-repo-id",
      url: "https://github.com/a/b",
      name: "b",
      status: "pending",
      created_at: "",
      latest_job: {
        id: "j1",
        repo_id: "some-repo-id",
        status: "running",
        progress: 40,
        error_message: null,
        skipped_files: 0,
        started_at: null,
        finished_at: null,
        stage: "parsing",
      },
    };
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => repo,
    }) as unknown as typeof fetch;

    render(<RepoWorkspacePage params={{ repoId: "some-repo-id" }} />);

    await waitFor(() => {
      expect(screen.getByText("Detecting domain & parsing AST...")).toBeInTheDocument();
    });
    expect(screen.queryByText(/briefing not available yet/i)).not.toBeInTheDocument();
  });

  it("shows the domain briefing once the repo is ready", async () => {
    const repo = {
      id: "some-repo-id",
      url: "https://github.com/a/b",
      name: "b",
      status: "ready",
      created_at: "",
      domain_briefing: {
        primary_field: "Full-Stack Web SaaS",
        target_audience: "Backend engineers",
        architecture_overview: "A FastAPI backend with a Next.js frontend.",
        tech_stack_badges: ["FastAPI", "Next.js"],
        file_type_distribution: [{ label: "Python backend files", count: 14 }],
      },
    };
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => repo,
    }) as unknown as typeof fetch;

    render(<RepoWorkspacePage params={{ repoId: "some-repo-id" }} />);

    await waitFor(() => {
      expect(screen.getByText("Full-Stack Web SaaS")).toBeInTheDocument();
    });
  });

  it("threads onCitationClick from ChatPanel down into CodeViewer's selected path", async () => {
    const repo = { id: "some-repo-id", url: "https://github.com/a/b", name: "b", status: "ready", created_at: "" };
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => repo,
    }) as unknown as typeof fetch;

    render(<RepoWorkspacePage params={{ repoId: "some-repo-id" }} />);

    await waitFor(() => {
      expect(screen.getByTestId("workspace-shell")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole("button", { name: "cite" }));

    await waitFor(() => {
      expect(screen.getByTestId("code-viewer")).toHaveTextContent("app/core/agent.py");
    });
  });
});
