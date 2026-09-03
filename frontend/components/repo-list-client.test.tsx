import { render, screen, waitFor } from "@testing-library/react";
import { RepoListClient } from "@/components/repo-list-client";

describe("RepoListClient", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("bootstraps the session then fetches and renders the repo list", async () => {
    const fetchMock = jest.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/auth/bootstrap")) {
        return Promise.resolve({ ok: true, json: async () => ({ ok: true }) });
      }
      return Promise.resolve({
        ok: true,
        json: async () => [{ id: "r1", url: "https://github.com/a/b", name: "b", status: "ready", created_at: "" }],
      });
    }) as unknown as typeof fetch;
    global.fetch = fetchMock;

    render(<RepoListClient />);

    expect(screen.getByLabelText("Loading repositories")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText("b")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/auth/bootstrap?format=json"));
    expect(fetchMock).toHaveBeenCalledWith("/api/repos", expect.objectContaining({ cache: "no-store" }));
  });

  it("shows the empty state when bootstrap succeeds but there are no repos yet", async () => {
    global.fetch = jest.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/auth/bootstrap")) {
        return Promise.resolve({ ok: true, json: async () => ({ ok: true }) });
      }
      return Promise.resolve({ ok: true, json: async () => [] });
    }) as unknown as typeof fetch;

    render(<RepoListClient />);

    await waitFor(() => expect(screen.getByText("No repositories yet. Submit one above to get started.")).toBeInTheDocument());
  });

  it("shows the 'can't reach the server' fallback when the repo fetch fails after bootstrap", async () => {
    global.fetch = jest.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/auth/bootstrap")) {
        return Promise.resolve({ ok: true, json: async () => ({ ok: true }) });
      }
      return Promise.resolve({ ok: false, status: 500 });
    }) as unknown as typeof fetch;

    render(<RepoListClient />);

    await waitFor(() => expect(screen.getByText("Can't reach the server")).toBeInTheDocument());
  });
});
