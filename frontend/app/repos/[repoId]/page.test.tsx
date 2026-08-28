import type { ReactNode } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RepoWorkspacePage from "./page";

// `mockSearchParams` (not `let searchParams`) so jest's module-factory
// hoisting allows referencing it inside `jest.mock` below -- the babel
// plugin that hoists `jest.mock` calls above imports only permits closing
// over out-of-scope identifiers whose name starts with "mock". Tests that
// need a `?job=` query param (the stage-driven refetch suite) reassign
// this before rendering; every other test gets the empty-params default.
let mockSearchParams = new URLSearchParams();
jest.mock("next/navigation", () => ({
  useSearchParams: () => mockSearchParams,
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
  // Renders the `stage` prop into the DOM (rather than ignoring it, as a
  // no-op mock would) so tests can assert that page.tsx is actually
  // threading the polled job's current stage down, not just that FileTree
  // renders at all.
  FileTree: ({ stage }: { stage?: string | null }) => <div data-testid="file-tree" data-stage={stage ?? ""} />,
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

describe("RepoWorkspacePage stage-driven refetch", () => {
  // Mirrors the backend pipeline change this frontend work lands against:
  // `File` rows and `repo.domain_briefing` are committed in their own
  // transaction right after parsing -- well before the job (still
  // `status: "running"`) reaches a terminal state. This suite mocks a job
  // whose `stage` changes from "parsing" to "embedding" between polls, with
  // `domain_briefing` only showing up in the `/api/repos/:id` response
  // *after* that transition -- exactly the scenario the fix targets -- and
  // confirms both the briefing card and the file tree's `stage` prop pick
  // it up without waiting for `status` to become terminal.
  beforeEach(() => {
    jest.useFakeTimers({ legacyFakeTimers: false });
    mockSearchParams = new URLSearchParams("job=job-1");
  });

  afterEach(() => {
    jest.useRealTimers();
    mockSearchParams = new URLSearchParams();
    jest.restoreAllMocks();
  });

  it("shows the briefing (alongside the progress stepper) and threads the new stage into FileTree as soon as the job moves from parsing to embedding -- before status is terminal", async () => {
    const briefing = {
      primary_field: "Full-Stack Web SaaS",
      target_audience: "Backend engineers",
      architecture_overview: "A FastAPI backend with a Next.js frontend.",
      tech_stack_badges: ["FastAPI", "Next.js"],
      file_type_distribution: [{ label: "Python backend files", count: 14 }],
    };

    let repoCallCount = 0;
    let jobCallCount = 0;

    global.fetch = jest.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();

      if (url === "/api/repos/some-repo-id") {
        repoCallCount += 1;
        // Only the 3rd repo fetch (triggered by the "parsing" -> "embedding"
        // stage transition below) reflects the now-populated briefing --
        // matching the backend committing it right after parsing finishes.
        const hasBriefingYet = repoCallCount >= 3;
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            id: "some-repo-id",
            url: "https://github.com/a/b",
            name: "b",
            status: "pending",
            created_at: "",
            domain_briefing: hasBriefingYet ? briefing : null,
          }),
        } as Response);
      }

      if (url === "/api/jobs/job-1") {
        jobCallCount += 1;
        const stage = jobCallCount === 1 ? "parsing" : "embedding";
        return Promise.resolve({
          ok: true,
          json: async () => ({
            id: "job-1",
            repo_id: "some-repo-id",
            status: "running",
            progress: jobCallCount === 1 ? 40 : 70,
            error_message: null,
            skipped_files: 0,
            started_at: null,
            finished_at: null,
            stage,
          }),
        } as Response);
      }

      throw new Error(`Unexpected fetch: ${url}`);
    }) as unknown as typeof fetch;

    render(<RepoWorkspacePage params={{ repoId: "some-repo-id" }} />);

    // Initial state: job's first poll reports "parsing", no briefing yet --
    // just the progress stepper, file tree gets stage="parsing".
    await waitFor(() => expect(screen.getByText("Detecting domain & parsing AST...")).toBeInTheDocument());
    expect(screen.queryByText("Full-Stack Web SaaS")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("file-tree")).toHaveAttribute("data-stage", "parsing"));

    // The job's next poll (2000ms later) reports "embedding" -- this is the
    // exact transition the backend change made meaningful: files/briefing
    // are already in the database at this point even though status is
    // still "running".
    await act(async () => {
      await jest.advanceTimersByTimeAsync(2000);
    });

    // The briefing card is now visible -- without waiting for the job to
    // reach a terminal status -- alongside the progress stepper, which
    // still shows the job is in the embedding stage.
    await waitFor(() => expect(screen.getByText("Full-Stack Web SaaS")).toBeInTheDocument());
    expect(screen.getByText("Generating CodeBERT embeddings...")).toBeInTheDocument();
    expect(screen.getByText(/still indexing/i)).toBeInTheDocument();

    // FileTree's `stage` prop followed the same transition, independent of
    // `polling` (which is still `true` throughout -- the job never reaches
    // a terminal state in this test).
    expect(screen.getByTestId("file-tree")).toHaveAttribute("data-stage", "embedding");
  });
});
