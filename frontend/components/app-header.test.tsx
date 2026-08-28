import { render, screen, waitFor } from "@testing-library/react";
import { AppHeader } from "./app-header";

// AppHeader renders SubmitRepoForm (compact), which calls useRouter() from
// next/navigation -- that throws "invariant expected app router to be
// mounted" outside a real app-router tree unless mocked, same as
// submit-repo-form.test.tsx already does for its own direct render.
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn(), refresh: jest.fn() }),
}));

describe("AppHeader", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("shows a repo URL input for quick submission", () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) }) as unknown as typeof fetch;
    render(<AppHeader />);
    expect(screen.getByLabelText("GitHub repository URL")).toBeInTheDocument();
  });

  it("shows a healthy indicator when the health check succeeds", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) }) as unknown as typeof fetch;
    render(<AppHeader />);
    await waitFor(() => expect(screen.getByLabelText("Backend healthy")).toBeInTheDocument());
  });

  it("shows an unhealthy indicator when the health check fails", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, json: async () => ({ ok: false }) }) as unknown as typeof fetch;
    render(<AppHeader />);
    await waitFor(() => expect(screen.getByLabelText("Backend unreachable")).toBeInTheDocument());
  });

  it("hides the GitHub link when NEXT_PUBLIC_GITHUB_REPO_URL is unset", () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) }) as unknown as typeof fetch;
    render(<AppHeader />);
    expect(screen.queryByRole("link", { name: /github/i })).not.toBeInTheDocument();
  });

  it("has no brand wordmark of its own -- AppSidebar is the sole home for it now", () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) }) as unknown as typeof fetch;
    render(<AppHeader />);
    expect(screen.queryByRole("link", { name: /repolens ai/i })).not.toBeInTheDocument();
  });
});
