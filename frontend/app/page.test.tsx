import { render, screen } from "@testing-library/react";

const store = new Map<string, string>();

// Same next/headers cookies() mock pattern as the proxy route tests (e.g.
// app/api/repos/[repoId]/files/route.test.ts) -- HomePage reads the session
// cookie directly via next/headers, not through a Route Handler.
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

import HomePage from "./page";
import { redirect } from "next/navigation";

describe("HomePage", () => {
  afterEach(() => {
    store.clear();
    jest.clearAllMocks();
  });

  it("renders a fallback instead of redirecting when no session cookie exists", () => {
    // This is what terminates the "/" <-> "/repos" redirect loop that can
    // happen if the middleware's guest-mint keeps failing (backend down):
    // without this check, HomePage would unconditionally redirect("/repos"),
    // which finds no token either and redirects back to "/", forever.
    render(<HomePage />);

    expect(screen.getByText(/having trouble connecting/i)).toBeInTheDocument();
    expect(redirect).not.toHaveBeenCalled();
  });

  it("redirects to /repos when a session cookie exists", () => {
    store.set("session_token", "guest-token-123");

    expect(() => render(<HomePage />)).toThrow("NEXT_REDIRECT:/repos");
    expect(redirect).toHaveBeenCalledWith("/repos");
  });
});
