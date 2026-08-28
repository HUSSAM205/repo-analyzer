import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FlagshipToolsModal } from "./flagship-tools-modal";

// ModuleMapViewer (unlike FlowMapViewer) fetches and renders automatically
// on mount rather than behind a "Generate" click -- simply switching to its
// tab is enough to reach mermaid.render(), which jsdom can't actually run
// (no real SVG/canvas layout), so it needs mocking here too.
jest.mock("mermaid", () => ({
  __esModule: true,
  default: {
    initialize: jest.fn(),
    render: jest.fn().mockResolvedValue({ svg: "<svg><g class=\"node\"><rect /></g></svg>" }),
  },
}));

describe("FlagshipToolsModal", () => {
  beforeEach(() => {
    global.fetch = jest.fn((url: string) => {
      if (typeof url === "string" && url.includes("/compliance-scan")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            overall_risk: "low",
            license_findings: [],
            secret_findings: [],
            dangerous_pattern_findings: [],
            disclaimer: "Pattern-based, not a substitute for a real audit.",
          }),
        });
      }
      if (typeof url === "string" && url.includes("/module-map")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ diagram: "flowchart TD\n  ROOT --> D0", directory_count: 1, file_count: 1 }),
        });
      }
      if (typeof url === "string" && url.includes("/routes")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ routes: [], frameworks_detected: [], disclaimer: "..." }),
        });
      }
      if (typeof url === "string" && url.includes("/bootstrap")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            stacks_detected: [],
            services_detected: [],
            dockerfile: "",
            docker_compose: "",
            setup_script: "",
          }),
        });
      }
      if (typeof url === "string" && url.includes("/complexity")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ functions_analyzed: 0, average_complexity: 0, hotspots: [], disclaimer: "..." }),
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({ entries: [] }) });
    }) as unknown as typeof fetch;
  });

  it("opens on Quick Start by default and switches tabs", async () => {
    const onClose = jest.fn();
    render(<FlagshipToolsModal repoId="r1" onClose={onClose} />);

    expect(screen.getByRole("tab", { name: /quick start/i })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText(/no recognized manifest file/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: /docs generator/i }));
    expect(screen.getByRole("tab", { name: /docs generator/i })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: /generate readme/i })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: /bug & security scan/i }));
    expect(screen.getByRole("button", { name: /run scan/i })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: /health score/i }));
    expect(screen.getByRole("button", { name: /compute score/i })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: /knowledge quiz/i }));
    expect(screen.getByRole("button", { name: /start quiz/i })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: /flow map/i }));
    expect(screen.getByRole("button", { name: /generate flow map/i })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: /module map/i }));
    expect(await screen.findByRole("img", { name: /directory\/module structure/i })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: /api explorer/i }));
    expect(await screen.findByText(/no fastapi, express, or next\.js/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: /bootstrapper/i }));
    expect(await screen.findByText(/couldn't detect a supported stack/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: /complexity radar/i }));
    expect(await screen.findByText(/no python\/js\/ts functions found/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: /regex playground/i }));
    expect(screen.getByLabelText("Regular expression pattern")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: /tech debt & roi/i }));
    expect(screen.getByRole("button", { name: /analyze tech debt/i })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: /compliance & licenses/i }));
    expect(await screen.findByText(/low overall risk/i)).toBeInTheDocument();
  });

  it("calls onClose when the close button is clicked", async () => {
    const onClose = jest.fn();
    render(<FlagshipToolsModal repoId="r1" onClose={onClose} />);

    await userEvent.click(screen.getByRole("button", { name: /close/i }));

    expect(onClose).toHaveBeenCalled();
  });

  it("calls onClose when clicking the backdrop but not when clicking inside the dialog", async () => {
    const onClose = jest.fn();
    render(<FlagshipToolsModal repoId="r1" onClose={onClose} />);

    await userEvent.click(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();

    // The backdrop is the dialog's parent -- click it directly.
    const dialog = screen.getByRole("dialog");
    await userEvent.click(dialog.parentElement as HTMLElement);
    expect(onClose).toHaveBeenCalled();
  });
});
