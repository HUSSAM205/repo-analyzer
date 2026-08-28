import { render, screen } from "@testing-library/react";
import { ComplexityRadarPanel } from "./complexity-radar-panel";

describe("ComplexityRadarPanel", () => {
  it("fetches automatically on mount and renders hotspots", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        functions_analyzed: 12,
        average_complexity: 3.4,
        hotspots: [
          { file: "app/core/agent.py", function: "assistant_node", line: 88, complexity: 14, maintainability: 22, line_count: 60 },
        ],
        disclaimer: "Keyword-based approximation, not audit-grade.",
      }),
    }) as unknown as typeof fetch;

    render(<ComplexityRadarPanel repoId="r1" />);

    expect(await screen.findByText("assistant_node")).toBeInTheDocument();
    expect(screen.getByText("14")).toBeInTheDocument();
    expect(screen.getByText("22")).toBeInTheDocument();
    expect(screen.getByText(/app\/core\/agent\.py:88/)).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
  });

  it("shows an empty state when no hotspots are found", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ functions_analyzed: 0, average_complexity: 0, hotspots: [], disclaimer: "..." }),
    }) as unknown as typeof fetch;

    render(<ComplexityRadarPanel repoId="r1" />);

    expect(await screen.findByText(/no python\/js\/ts functions found/i)).toBeInTheDocument();
  });

  it("shows the backend's error message on failure", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "This repository hasn't finished analyzing yet." }),
    }) as unknown as typeof fetch;

    render(<ComplexityRadarPanel repoId="r1" />);

    expect(await screen.findByText("This repository hasn't finished analyzing yet.")).toBeInTheDocument();
  });
});
