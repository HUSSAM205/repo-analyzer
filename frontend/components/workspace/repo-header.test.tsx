import { render, screen } from "@testing-library/react";
import { RepoHeader } from "./repo-header";
import type { Repo } from "@/lib/types";

const repo: Repo = { id: "r1", url: "https://github.com/octocat/Hello-World", name: "Hello-World", status: "ready", created_at: "" };

describe("RepoHeader", () => {
  it("renders the repo name and a ready status dot", () => {
    render(<RepoHeader repo={repo} job={null} polling={false} />);
    expect(screen.getByText("Hello-World")).toBeInTheDocument();
  });

  it("has no sign-out control", () => {
    render(<RepoHeader repo={repo} job={null} polling={false} />);
    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
  });
});
