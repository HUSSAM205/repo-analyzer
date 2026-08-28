import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouteExplorerPanel } from "./route-explorer-panel";

describe("RouteExplorerPanel", () => {
  it("fetches automatically on mount and renders a routes table", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        routes: [
          {
            method: "GET",
            path: "/api/v1/repos/{repo_id}",
            file: "app/api/routes/repos.py",
            line: 12,
            framework: "fastapi",
            path_params: ["repo_id"],
            auth_required: true,
          },
        ],
        frameworks_detected: ["fastapi"],
        disclaimer: "Pattern-based extraction, not a runtime guarantee.",
      }),
    }) as unknown as typeof fetch;

    render(<RouteExplorerPanel repoId="r1" />);

    expect(await screen.findByText("GET")).toBeInTheDocument();
    expect(screen.getByText("/api/v1/repos/{repo_id}")).toBeInTheDocument();
    expect(screen.getByText("Required")).toBeInTheDocument();
    expect(screen.getByText(/app\/api\/routes\/repos\.py:12/)).toBeInTheDocument();
  });

  it("offers a Markdown/OpenAPI export once routes are loaded", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        routes: [
          { method: "GET", path: "/health", file: "main.py", line: 1, framework: "fastapi", path_params: [], auth_required: false },
        ],
        frameworks_detected: ["fastapi"],
        disclaimer: "...",
      }),
    }) as unknown as typeof fetch;

    render(<RouteExplorerPanel repoId="r1" />);
    await screen.findByText("GET");

    await userEvent.click(screen.getByRole("button", { name: /export/i }));

    expect(screen.getByRole("menuitem", { name: "Markdown" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "OpenAPI (JSON)" })).toBeInTheDocument();
  });

  it("shows an empty state when no routes are found", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ routes: [], frameworks_detected: [], disclaimer: "..." }),
    }) as unknown as typeof fetch;

    render(<RouteExplorerPanel repoId="r1" />);

    expect(await screen.findByText(/no fastapi, express, or next\.js/i)).toBeInTheDocument();
  });

  it("filters the table by framework when multiple frameworks are detected", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        routes: [
          { method: "GET", path: "/health", file: "main.py", line: 1, framework: "fastapi", path_params: [], auth_required: false },
          { method: "GET", path: "/ping", file: "index.js", line: 1, framework: "express", path_params: [], auth_required: false },
        ],
        frameworks_detected: ["express", "fastapi"],
        disclaimer: "...",
      }),
    }) as unknown as typeof fetch;

    render(<RouteExplorerPanel repoId="r1" />);
    await screen.findByText("/health");
    expect(screen.getByText("/ping")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /^fastapi$/i }));

    expect(screen.getByText("/health")).toBeInTheDocument();
    expect(screen.queryByText("/ping")).not.toBeInTheDocument();
  });

  it("shows the backend's error message on failure", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "This repository hasn't finished analyzing yet." }),
    }) as unknown as typeof fetch;

    render(<RouteExplorerPanel repoId="r1" />);

    expect(await screen.findByText("This repository hasn't finished analyzing yet.")).toBeInTheDocument();
  });
});
