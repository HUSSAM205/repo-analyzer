import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HealthScorecard } from "./health-scorecard";

describe("HealthScorecard", () => {
  it("computes and renders the score breakdown", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        overall_score: 78,
        sub_scores: { documentation: 100, testing: 60, automation: 70, quality: 82 },
        commentary: "Clean and consistent code.",
        signals: { has_readme: true, has_tests: true, has_ci: true, has_license: false },
      }),
    }) as unknown as typeof fetch;

    render(<HealthScorecard repoId="r1" />);
    await userEvent.click(screen.getByRole("button", { name: /compute score/i }));

    expect(await screen.findByText("78")).toBeInTheDocument();
    expect(screen.getByText("Overall Score")).toBeInTheDocument();
    expect(screen.getByText("Documentation")).toBeInTheDocument();
    expect(screen.getByText("Clean and consistent code.")).toBeInTheDocument();
  });

  it("shows the backend's error message on failure", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "Could not compute the score." }),
    }) as unknown as typeof fetch;

    render(<HealthScorecard repoId="r1" />);
    await userEvent.click(screen.getByRole("button", { name: /compute score/i }));

    expect(await screen.findByText("Could not compute the score.")).toBeInTheDocument();
  });
});
