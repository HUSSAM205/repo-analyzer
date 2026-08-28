import { render, screen } from "@testing-library/react";
import { RepoList } from "./repo-list";
import type { Repo } from "@/lib/types";

function _repo(overrides: Partial<Repo>): Repo {
  return {
    id: "r1",
    url: "https://github.com/owner/repo",
    name: "repo",
    status: "ready",
    created_at: "",
    ...overrides,
  } as Repo;
}

describe("RepoList", () => {
  it("shows the empty state when there are no repos", () => {
    render(<RepoList repos={[]} />);
    expect(screen.getByText(/no repositories yet/i)).toBeInTheDocument();
  });

  it("renders each repo as a card linking to its detail page, with name and status", () => {
    const repos = [
      _repo({ id: "r1", name: "express", status: "ready" }),
      _repo({ id: "r2", name: "fastapi", status: "pending" }),
      _repo({ id: "r3", name: "redux", status: "failed" }),
    ];
    render(<RepoList repos={repos} />);

    expect(screen.getByText("express")).toBeInTheDocument();
    expect(screen.getByText("fastapi")).toBeInTheDocument();
    expect(screen.getByText("redux")).toBeInTheDocument();
    expect(screen.getByText("ready")).toBeInTheDocument();
    expect(screen.getByText("pending")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();

    const link = screen.getByText("express").closest("a");
    expect(link).toHaveAttribute("href", "/repos/r1");
  });

  it("renders repos in a grid, not a single-column list", () => {
    render(<RepoList repos={[_repo({ id: "r1" })]} />);
    const list = screen.getByText("repo").closest("ul");
    expect(list).toHaveClass("grid");
  });
});
