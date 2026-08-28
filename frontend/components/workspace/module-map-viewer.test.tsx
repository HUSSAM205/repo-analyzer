import { render, screen, waitFor } from "@testing-library/react";
import { ModuleMapViewer } from "./module-map-viewer";

jest.mock("mermaid", () => ({
  __esModule: true,
  default: {
    initialize: jest.fn(),
    render: jest.fn().mockResolvedValue({ svg: "<svg><g class=\"node\"><rect /></g></svg>" }),
  },
}));

describe("ModuleMapViewer", () => {
  it("fetches automatically on mount and renders the diagram as SVG", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ diagram: "flowchart TD\n  ROOT --> D0", directory_count: 3, file_count: 42 }),
    }) as unknown as typeof fetch;

    render(<ModuleMapViewer repoId="r1" />);

    await waitFor(() => expect(screen.getByRole("img", { name: /directory\/module structure/i })).toBeInTheDocument());
    const container = screen.getByRole("img", { name: /directory\/module structure/i });
    expect(container.innerHTML).toContain("<svg>");
    expect(screen.getByText(/42 files across 3 top-level directories/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /export/i })).toBeInTheDocument();
  });

  it("shows the backend's error message on failure", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "This repository hasn't finished analyzing yet." }),
    }) as unknown as typeof fetch;

    render(<ModuleMapViewer repoId="r1" />);

    expect(await screen.findByText("This repository hasn't finished analyzing yet.")).toBeInTheDocument();
  });
});
