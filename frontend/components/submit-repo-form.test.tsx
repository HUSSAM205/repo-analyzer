import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SubmitRepoForm } from "./submit-repo-form";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn(), refresh: jest.fn() }),
}));

describe("SubmitRepoForm", () => {
  beforeEach(() => {
    global.fetch = jest.fn();
  });

  it("submits the URL and shows a submitting state", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ repo_id: "r1", job_id: "j1" }),
    });

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
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ repo_id: "r1", job_id: "j1" }),
    });

    render(<SubmitRepoForm />);
    const input = screen.getByLabelText("GitHub repository URL") as HTMLInputElement;
    await userEvent.type(input, "https://github.com/octocat/Hello-World");
    await userEvent.click(screen.getByRole("button", { name: /analyze/i }));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalled();
    });

    expect(input.value).toBe("https://github.com/octocat/Hello-World");
  });

  it("shows the backend's error message on failure", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: "Rate limit exceeded" }),
    });

    render(<SubmitRepoForm />);
    await userEvent.type(screen.getByLabelText("GitHub repository URL"), "https://github.com/a/b");
    await userEvent.click(screen.getByRole("button", { name: /analyze/i }));

    expect(await screen.findByText("Rate limit exceeded")).toBeInTheDocument();
  });
});
