import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FlowMapViewer } from "./flow-map-viewer";

jest.mock("mermaid", () => ({
  __esModule: true,
  default: {
    initialize: jest.fn(),
    render: jest.fn().mockResolvedValue({ svg: "<svg><g class=\"node\"><rect /></g></svg>" }),
  },
}));

describe("FlowMapViewer", () => {
  it("fetches the diagram and renders it as SVG", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ diagram: "flowchart TD\n  A --> B" }),
    }) as unknown as typeof fetch;

    render(<FlowMapViewer repoId="r1" />);
    await userEvent.click(screen.getByRole("button", { name: /generate flow map/i }));

    await waitFor(() => expect(screen.getByRole("img", { name: /architecture flow diagram/i })).toBeInTheDocument());
    const container = screen.getByRole("img", { name: /architecture flow diagram/i });
    expect(container.innerHTML).toContain("<svg>");
    expect(screen.getByRole("button", { name: /export/i })).toBeInTheDocument();
  });

  it("shows the backend's error message on failure", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "Could not generate the architecture diagram." }),
    }) as unknown as typeof fetch;

    render(<FlowMapViewer repoId="r1" />);
    await userEvent.click(screen.getByRole("button", { name: /generate flow map/i }));

    expect(await screen.findByText("Could not generate the architecture diagram.")).toBeInTheDocument();
  });
});
