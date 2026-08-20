import { render, screen } from "@testing-library/react";

const store = new Map<string, string>();

// Same next/headers cookies() mock pattern as app/page.test.tsx and the
// proxy route tests -- ReposPage reads the session cookie directly via
// next/headers, not through a Route Handler.
jest.mock("next/headers", () => ({
  cookies: () => ({
    get: (name: string) => (store.has(name) ? { value: store.get(name) } : undefined),
  }),
}));

jest.mock("next/navigation", () => ({
  redirect: jest.fn((url: string) => {
    throw new Error(`NEXT_REDIRECT:${url}`);
  }),
}));

import ReposPage from "./page";

describe("ReposPage", () => {
  beforeEach(() => {
    store.set("session_token", "guest-token-123");
  });

  afterEach(() => {
    store.clear();
    jest.clearAllMocks();
  });

  it("shows an in-theme 'can't reach the server' fallback instead of crashing when the backend fetch throws", async () => {
    // Before the fix, an unguarded `await fetch(...)` here threw inside a
    // Server Component render -- with no app/error.tsx anywhere in the
    // project, that crashed straight to Next's generic unthemed error page.
    global.fetch = jest.fn().mockRejectedValue(new TypeError("Failed to fetch")) as unknown as typeof fetch;

    const ui = await ReposPage();
    render(ui);

    expect(screen.getByText("Can't reach the server")).toBeInTheDocument();
  });

  it("shows the same fallback (not a crash) when the backend responds with a non-ok status", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ detail: "Internal Server Error" }),
    }) as unknown as typeof fetch;

    const ui = await ReposPage();
    render(ui);

    expect(screen.getByText("Can't reach the server")).toBeInTheDocument();
  });

  it("renders the repo list normally when the backend responds", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [{ id: "r1", url: "https://github.com/a/b", name: "b", status: "ready", created_at: "" }],
    }) as unknown as typeof fetch;

    const ui = await ReposPage();
    render(ui);

    expect(screen.getByText("b")).toBeInTheDocument();
    expect(screen.queryByText("Can't reach the server")).not.toBeInTheDocument();
  });

  it("redirects through /api/auth/reset when there's no session cookie", async () => {
    store.clear();

    await expect(ReposPage()).rejects.toThrow("NEXT_REDIRECT:/api/auth/reset");
  });
});
