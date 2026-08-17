import type { ReactNode } from "react";
import { render, screen, waitFor } from "@testing-library/react";
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
  CodeViewer: () => <div data-testid="code-viewer" />,
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
      json: async () => [repo],
    }) as unknown as typeof fetch;

    render(<RepoWorkspacePage params={{ repoId: "some-repo-id" }} />);

    await waitFor(() => {
      expect(screen.getByTestId("workspace-shell")).toBeInTheDocument();
    });

    expect(screen.getByTestId("repo-header")).toBeInTheDocument();
    expect(screen.queryByText("Could not load this repository.")).not.toBeInTheDocument();
  });
});
