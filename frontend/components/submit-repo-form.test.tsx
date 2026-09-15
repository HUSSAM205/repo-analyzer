import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SubmitRepoForm } from "./submit-repo-form";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn(), refresh: jest.fn() }),
}));

// submit() now awaits the shared, deduped session-bootstrap fetch (see
// lib/session-bootstrap.ts) before the real POST /api/repos -- a bare
// sequential `mockResolvedValueOnce` queue would hand that first response
// to the bootstrap call instead of the one each test actually cares about.
// A URL-aware mock sidesteps that regardless of how many times bootstrap
// itself gets called (it's deduped at the module level, so in practice
// that's usually just once across this whole file).
function mockFetchForAnalyze(analyzeResponse: { ok: boolean; json: () => Promise<unknown> }) {
  global.fetch = jest.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/auth/bootstrap")) {
      return Promise.resolve({ ok: true, json: async () => ({ ok: true }) });
    }
    return Promise.resolve(analyzeResponse);
  }) as unknown as typeof fetch;
}

describe("SubmitRepoForm", () => {
  beforeEach(() => {
    global.fetch = jest.fn();
  });

  it("submits the URL and shows a submitting state", async () => {
    mockFetchForAnalyze({ ok: true, json: async () => ({ repo_id: "r1", job_id: "j1" }) });

    render(<SubmitRepoForm />);
    const input = screen.getByLabelText("GitHub repository URL");
    await userEvent.type(input, "https://github.com/octocat/Hello-World");
    await userEvent.click(screen.getByRole("button", { name: /analyze/i }));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        "/api/repos",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ repo_url: "https://github.com/octocat/Hello-World" }),
        })
      );
    });
  });

  it("does not clear the URL after a successful submit (it lives in a persistent layout header)", async () => {
    mockFetchForAnalyze({ ok: true, json: async () => ({ repo_id: "r1", job_id: "j1" }) });

    render(<SubmitRepoForm />);
    const input = screen.getByLabelText("GitHub repository URL") as HTMLInputElement;
    await userEvent.type(input, "https://github.com/octocat/Hello-World");
    await userEvent.click(screen.getByRole("button", { name: /analyze/i }));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith("/api/repos", expect.anything());
    });

    expect(input.value).toBe("https://github.com/octocat/Hello-World");
  });

  it("shows a valid-URL checkmark once a well-formed GitHub URL is typed (non-compact only)", async () => {
    render(<SubmitRepoForm />);
    const input = screen.getByLabelText("GitHub repository URL");

    expect(screen.queryByLabelText("Valid GitHub repository URL")).not.toBeInTheDocument();

    await userEvent.type(input, "https://github.com/octocat/Hello-World");

    expect(screen.getByLabelText("Valid GitHub repository URL")).toBeInTheDocument();
  });

  it("does not show the command-bar chrome (kbd hint, checkmark) in compact mode", async () => {
    render(<SubmitRepoForm compact />);
    const input = screen.getByLabelText("GitHub repository URL");

    await userEvent.type(input, "https://github.com/octocat/Hello-World");

    expect(screen.queryByLabelText("Valid GitHub repository URL")).not.toBeInTheDocument();
  });

  it("shows the backend's error message on failure", async () => {
    mockFetchForAnalyze({ ok: false, json: async () => ({ detail: "Rate limit exceeded" }) });

    render(<SubmitRepoForm />);
    await userEvent.type(screen.getByLabelText("GitHub repository URL"), "https://github.com/a/b");
    await userEvent.click(screen.getByRole("button", { name: /analyze/i }));

    expect(await screen.findByText("Rate limit exceeded")).toBeInTheDocument();
  });
});
