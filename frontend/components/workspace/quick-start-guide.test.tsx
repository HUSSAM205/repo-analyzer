import { render, screen } from "@testing-library/react";
import { QuickStartGuide } from "./quick-start-guide";

describe("QuickStartGuide", () => {
  it("detects npm install/run steps from a package.json at the root", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        entries: [
          { name: "package.json", path: "package.json", type: "file", children: null },
          { name: "src", path: "src", type: "directory", children: [
            { name: "index.js", path: "src/index.js", type: "file", children: null },
          ] },
        ],
      }),
    }) as unknown as typeof fetch;

    render(<QuickStartGuide repoId="r1" />);

    expect(await screen.findByText("npm install")).toBeInTheDocument();
    expect(screen.getByText("npm run dev")).toBeInTheDocument();
  });

  it("detects a Python venv + pip install flow from requirements.txt", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        entries: [{ name: "requirements.txt", path: "requirements.txt", type: "file", children: null }],
      }),
    }) as unknown as typeof fetch;

    render(<QuickStartGuide repoId="r1" />);

    expect(await screen.findByText("pip install -r requirements.txt")).toBeInTheDocument();
  });

  it("shows a fallback message when no recognized manifest is found", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ entries: [{ name: "notes.txt", path: "notes.txt", type: "file", children: null }] }),
    }) as unknown as typeof fetch;

    render(<QuickStartGuide repoId="r1" />);

    expect(await screen.findByText(/no recognized manifest file/i)).toBeInTheDocument();
  });

  it("shows an error message when the file tree fails to load", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false }) as unknown as typeof fetch;

    render(<QuickStartGuide repoId="r1" />);

    expect(await screen.findByText(/could not load the file tree/i)).toBeInTheDocument();
  });
});
