import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReportsModal } from "./reports-modal";

jest.mock("mermaid", () => ({
  __esModule: true,
  default: {
    initialize: jest.fn(),
    render: jest.fn().mockResolvedValue({ svg: "<svg><g class=\"node\"><rect /></g></svg>" }),
  },
}));

describe("ReportsModal", () => {
  beforeEach(() => {
    global.fetch = jest.fn((url: string) => {
      if (typeof url === "string" && url.includes("/compliance-scan")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            overall_risk: "low", license_findings: [], secret_findings: [], dangerous_pattern_findings: [], disclaimer: "...",
          }),
        });
      }
      if (typeof url === "string" && url.includes("/module-map")) {
        return Promise.resolve({ ok: true, json: async () => ({ diagram: "flowchart TD\n  ROOT --> D0", directory_count: 1, file_count: 1 }) });
      }
      if (typeof url === "string" && url.includes("/routes")) {
        return Promise.resolve({ ok: true, json: async () => ({ routes: [], frameworks_detected: [], disclaimer: "..." }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({ diagram: "flowchart TD" }) });
    }) as unknown as typeof fetch;
  });

  it("opens on Compliance & Licenses by default and switches between the four report tabs", async () => {
    render(<ReportsModal repoId="r1" onClose={jest.fn()} />);

    expect(screen.getByRole("tab", { name: /compliance & licenses/i })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText(/low overall risk/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: /api explorer/i }));
    expect(await screen.findByText(/no fastapi, express, or next\.js/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: /module map/i }));
    expect(await screen.findByRole("img", { name: /directory\/module structure/i })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: /flow map/i }));
    expect(screen.getByRole("button", { name: /generate flow map/i })).toBeInTheDocument();
  });

  it("calls onClose when the close button is clicked", async () => {
    const onClose = jest.fn();
    render(<ReportsModal repoId="r1" onClose={onClose} />);

    await userEvent.click(screen.getByRole("button", { name: /close/i }));

    expect(onClose).toHaveBeenCalled();
  });
});
