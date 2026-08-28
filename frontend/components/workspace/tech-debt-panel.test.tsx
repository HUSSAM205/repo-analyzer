import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TechDebtPanel } from "./tech-debt-panel";

describe("TechDebtPanel", () => {
  it("computes and renders the debt report with before/after snippets", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        estimated_debt_hours: 4.5,
        summary: "Some duplicated validation logic across handlers.",
        items: [
          {
            file: "main.py",
            issue: "Duplicated validation",
            estimated_hours: 4.5,
            before_snippet: "if x: pass\nif x: pass",
            after_snippet: "def check(x): return x",
            explanation: "Deduplicates the check into one function.",
          },
        ],
      }),
    }) as unknown as typeof fetch;

    render(<TechDebtPanel repoId="r1" />);
    await userEvent.click(screen.getByRole("button", { name: /analyze tech debt/i }));

    expect(await screen.findByText("4.5h")).toBeInTheDocument();
    expect(screen.getByText("Duplicated validation")).toBeInTheDocument();
    expect(screen.getByText("def check(x): return x")).toBeInTheDocument();
  });

  it("shows a clean-codebase message when there are no items", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ estimated_debt_hours: 0, summary: "Looks clean.", items: [] }),
    }) as unknown as typeof fetch;

    render(<TechDebtPanel repoId="r1" />);
    await userEvent.click(screen.getByRole("button", { name: /analyze tech debt/i }));

    expect(await screen.findByText(/no significant technical debt found/i)).toBeInTheDocument();
  });

  it("shows the backend's error message on failure", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "Could not generate the technical debt report." }),
    }) as unknown as typeof fetch;

    render(<TechDebtPanel repoId="r1" />);
    await userEvent.click(screen.getByRole("button", { name: /analyze tech debt/i }));

    expect(await screen.findByText("Could not generate the technical debt report.")).toBeInTheDocument();
  });
});
