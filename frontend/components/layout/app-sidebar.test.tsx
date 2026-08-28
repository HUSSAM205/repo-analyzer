import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppSidebar } from "./app-sidebar";

let mockPathname = "/repos";
jest.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
}));

function setPathname(pathname: string) {
  mockPathname = pathname;
}

// The Reports modal mounts real, already-tested panels (CompliancePanel,
// RouteExplorerPanel, ModuleMapViewer, FlowMapViewer) that each fetch their
// own shaped response and would crash on a generic `[]` -- a URL-aware
// mock keeps every one of them past its own render, the same way each
// panel's own test suite mocks fetch for itself.
function mockFetchByUrl() {
  global.fetch = jest.fn((url: string) => {
    if (url.includes("/compliance-scan")) {
      return Promise.resolve({
        ok: true,
        json: async () => ({
          overall_risk: "low", license_findings: [], secret_findings: [], dangerous_pattern_findings: [], disclaimer: "",
        }),
      });
    }
    if (url.includes("/routes")) {
      return Promise.resolve({ ok: true, json: async () => ({ routes: [], frameworks_detected: [], disclaimer: "" }) });
    }
    if (url.includes("/module-map")) {
      return Promise.resolve({ ok: true, json: async () => ({ diagram: "flowchart TD", directory_count: 0, file_count: 0 }) });
    }
    if (url.includes("/flow-map")) {
      return Promise.resolve({ ok: true, json: async () => ({ diagram: "flowchart TD" }) });
    }
    // /api/repos (Past Analyzed Repos) and anything else -- an empty list.
    return Promise.resolve({ ok: true, json: async () => [] });
  }) as unknown as typeof fetch;
}

describe("AppSidebar", () => {
  beforeEach(() => {
    setPathname("/repos");
    window.localStorage.clear();
    mockFetchByUrl();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("renders the brand header and both nav sections with no duplicate items", () => {
    render(<AppSidebar />);

    expect(screen.getByText("RepoLens AI")).toBeInTheDocument();
    expect(screen.getByText("Powered & Managed by Easy Solutions")).toBeInTheDocument();
    expect(screen.getByText("Core")).toBeInTheDocument();
    expect(screen.getByText("Management")).toBeInTheDocument();

    for (const label of ["AI Chatbot", "Repos", "Tools", "Past Analyzed Repos", "Feedback", "Reports", "Settings"]) {
      expect(screen.getAllByText(label)).toHaveLength(1);
    }
  });

  it("disables AI Chatbot, Tools, and Reports when no repo is active", () => {
    setPathname("/repos");
    render(<AppSidebar />);

    expect(screen.getByRole("button", { name: "AI Chatbot" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Tools" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reports" })).toBeDisabled();
  });

  it("enables AI Chatbot as a link into the chat tab, and Tools/Reports as triggers, when a repo is active", async () => {
    setPathname("/repos/11111111-1111-1111-1111-111111111111");
    render(<AppSidebar />);

    const chatLink = screen.getByRole("link", { name: "AI Chatbot" });
    expect(chatLink).toHaveAttribute("href", "/repos/11111111-1111-1111-1111-111111111111?tab=chat");

    await userEvent.click(screen.getByRole("button", { name: "Tools" }));
    expect(screen.getByRole("dialog", { name: /flagship tools/i })).toBeInTheDocument();
  });

  it("opens the Reports modal, scoped to the active repo, when Reports is clicked", async () => {
    setPathname("/repos/11111111-1111-1111-1111-111111111111");
    render(<AppSidebar />);

    await userEvent.click(screen.getByRole("button", { name: "Reports" }));
    expect(screen.getByRole("dialog", { name: "Reports" })).toBeInTheDocument();
  });

  it("opens the Feedback modal from anywhere, regardless of an active repo", async () => {
    setPathname("/repos");
    render(<AppSidebar />);

    await userEvent.click(screen.getByRole("button", { name: "Feedback" }));
    expect(screen.getByRole("dialog", { name: "Feedback" })).toBeInTheDocument();
  });

  it("expands Past Analyzed Repos and lists fetched repos as links", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => [{ id: "r1", url: "https://github.com/x/y", name: "y", status: "ready", created_at: "" }],
    }) as unknown as typeof fetch;

    render(<AppSidebar />);

    await userEvent.click(screen.getByRole("button", { name: /past analyzed repos/i }));

    const link = await screen.findByRole("link", { name: "y" });
    expect(link).toHaveAttribute("href", "/repos/r1");
  });

  it("collapses the desktop sidebar and persists the preference across remounts", async () => {
    const { unmount } = render(<AppSidebar />);

    await userEvent.click(screen.getByRole("button", { name: /collapse sidebar/i }));
    expect(screen.queryByText("RepoLens AI")).not.toBeInTheDocument();

    unmount();
    render(<AppSidebar />);
    await waitFor(() => expect(screen.queryByText("RepoLens AI")).not.toBeInTheDocument());
  });

  it("opens and closes the mobile drawer", async () => {
    render(<AppSidebar />);

    // jsdom has no real viewport, so the always-rendered desktop rail's own
    // "RepoLens AI" brand text is already present before the drawer opens --
    // opening it adds a second copy (the drawer's own SidebarContent).
    expect(screen.getAllByText("RepoLens AI")).toHaveLength(1);

    await userEvent.click(screen.getByRole("button", { name: /open navigation menu/i }));
    expect(screen.getAllByText("RepoLens AI")).toHaveLength(2);

    await userEvent.click(screen.getByRole("button", { name: /close navigation menu/i }));
    // AnimatePresence's exit animation keeps the drawer mounted for a beat
    // after the click -- wait for it to actually finish unmounting rather
    // than asserting immediately.
    await waitFor(() => expect(screen.queryByRole("button", { name: /close navigation menu/i })).not.toBeInTheDocument());
    expect(screen.getAllByText("RepoLens AI")).toHaveLength(1);
  });
});
