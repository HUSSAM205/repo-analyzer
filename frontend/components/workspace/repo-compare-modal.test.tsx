import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RepoCompareModal } from "./repo-compare-modal";
import type { Repo, RepoCompareResponse } from "@/lib/types";

const otherRepos: Repo[] = [
  { id: "r2", url: "https://github.com/x/repo-b", name: "repo-b", status: "ready", created_at: "" },
  { id: "r3", url: "https://github.com/x/repo-c", name: "repo-c", status: "ready", created_at: "" },
  { id: "r4", url: "https://github.com/x/not-ready", name: "not-ready", status: "pending", created_at: "" },
];

const compareResult: RepoCompareResponse = {
  repo_a: {
    repo_id: "r1",
    name: "repo-a",
    url: "https://github.com/x/repo-a",
    metrics: {
      file_count: 10,
      lines_of_code: 500,
      average_complexity: 3.2,
      functions_analyzed: 20,
      route_count: 4,
      frameworks_detected: ["fastapi"],
      vulnerability_count: 1,
      overall_risk: "low",
      module_breakdown: { app: 8, tests: 2 },
    },
  },
  repo_b: {
    repo_id: "r2",
    name: "repo-b",
    url: "https://github.com/x/repo-b",
    metrics: {
      file_count: 15,
      lines_of_code: 800,
      average_complexity: 5.1,
      functions_analyzed: 35,
      route_count: 6,
      frameworks_detected: ["express"],
      vulnerability_count: 3,
      overall_risk: "medium",
      module_breakdown: { src: 15 },
    },
  },
  deltas: {
    file_count_delta: 5,
    lines_of_code_delta: 300,
    average_complexity_delta: 1.9,
    route_count_delta: 2,
    vulnerability_count_delta: 2,
  },
  security_verdict: "Repo A has the stronger security posture -- lower overall risk (low vs medium).",
  disclaimer: "All metrics are computed locally...",
};

function mockFetchSequence(responses: { ok: boolean; json: () => unknown }[]) {
  let call = 0;
  global.fetch = jest.fn().mockImplementation(() => {
    const response = responses[Math.min(call, responses.length - 1)];
    call += 1;
    return Promise.resolve({ ok: response.ok, json: async () => response.json() } as Response);
  }) as unknown as typeof fetch;
}

describe("RepoCompareModal", () => {
  it("loads the user's other ready repos into the picker, excluding the current repo and non-ready ones", async () => {
    mockFetchSequence([{ ok: true, json: () => otherRepos }]);

    render(<RepoCompareModal repoId="r1" repoName="repo-a" onClose={jest.fn()} />);

    await waitFor(() => expect(screen.getByRole("combobox", { name: /repo b/i })).toBeInTheDocument());
    expect(screen.getByRole("option", { name: "repo-b" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "repo-c" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "not-ready" })).not.toBeInTheDocument();
  });

  it("shows an empty state when there are no other ready repos to compare against", async () => {
    mockFetchSequence([{ ok: true, json: () => [] }]);

    render(<RepoCompareModal repoId="r1" repoName="repo-a" onClose={jest.fn()} />);

    expect(await screen.findByText(/no other analyzed repositories yet/i)).toBeInTheDocument();
  });

  it("runs the comparison and renders both repos' metrics, deltas, and the security verdict", async () => {
    mockFetchSequence([{ ok: true, json: () => otherRepos }, { ok: true, json: () => compareResult }]);

    render(<RepoCompareModal repoId="r1" repoName="repo-a" onClose={jest.fn()} />);

    await waitFor(() => expect(screen.getByRole("combobox", { name: /repo b/i })).toBeInTheDocument());
    await userEvent.selectOptions(screen.getByRole("combobox", { name: /repo b/i }), "r2");
    await userEvent.click(screen.getByRole("button", { name: /^compare$/i }));

    expect(await screen.findByText(/stronger security posture/i)).toBeInTheDocument();
    expect(screen.getByText("repo-a")).toBeInTheDocument();
    expect(screen.getByText("repo-b")).toBeInTheDocument();
    expect(screen.getAllByText("low risk", { exact: false }).length).toBeGreaterThan(0);
    expect(screen.getAllByText("medium risk", { exact: false }).length).toBeGreaterThan(0);
  });

  it("shows the backend's error message on failure", async () => {
    mockFetchSequence([
      { ok: true, json: () => otherRepos },
      { ok: false, json: () => ({ detail: "This repository hasn't finished analyzing yet." }) },
    ]);

    render(<RepoCompareModal repoId="r1" repoName="repo-a" onClose={jest.fn()} />);

    await waitFor(() => expect(screen.getByRole("combobox", { name: /repo b/i })).toBeInTheDocument());
    await userEvent.selectOptions(screen.getByRole("combobox", { name: /repo b/i }), "r2");
    await userEvent.click(screen.getByRole("button", { name: /^compare$/i }));

    expect(await screen.findByText("This repository hasn't finished analyzing yet.")).toBeInTheDocument();
  });

  it("calls onClose when the backdrop is clicked", async () => {
    mockFetchSequence([{ ok: true, json: () => [] }]);
    const onClose = jest.fn();

    render(<RepoCompareModal repoId="r1" repoName="repo-a" onClose={onClose} />);

    await userEvent.click(screen.getByRole("dialog", { name: /compare repositories/i }).parentElement as HTMLElement);
    expect(onClose).toHaveBeenCalled();
  });
});
