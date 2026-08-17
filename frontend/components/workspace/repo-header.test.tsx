import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RepoHeader } from "./repo-header";
import type { Repo } from "@/lib/types";

const push = jest.fn();
const refresh = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh }),
}));

const repo: Repo = { id: "r1", url: "https://github.com/octocat/Hello-World", name: "Hello-World", status: "ready", created_at: "" };

describe("RepoHeader sign-out", () => {
  afterEach(() => {
    jest.restoreAllMocks();
    push.mockClear();
    refresh.mockClear();
  });

  it("posts to the logout route and redirects to /login when Sign out is clicked", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) }) as unknown as typeof fetch;

    render(<RepoHeader repo={repo} job={null} polling={false} />);

    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));

    expect(fetch).toHaveBeenCalledWith("/api/auth/logout", { method: "POST" });
    expect(push).toHaveBeenCalledWith("/login");
    expect(refresh).toHaveBeenCalled();
  });

  it("still redirects to /login even if the logout request fails", async () => {
    // A signed-out redirect shouldn't get stuck just because the network
    // blipped -- the user's intent to leave should win either way.
    global.fetch = jest.fn().mockRejectedValue(new Error("network error")) as unknown as typeof fetch;

    render(<RepoHeader repo={repo} job={null} polling={false} />);

    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));

    expect(push).toHaveBeenCalledWith("/login");
  });
});
