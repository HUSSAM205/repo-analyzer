import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CodeViewer } from "./code-viewer";

// Real Shiki's WASM cold-start is CPU-intensive and contention-sensitive
// (see lib/highlight.test.ts, which needs an explicit 15000ms timeout for
// the same highlightCode() call). This is a component-level test -- it
// shouldn't depend on the real syntax highlighter at all, so mock it out.
jest.mock("../../lib/highlight", () => ({
  highlightCode: async (code: string) => `<pre><code>${code}</code></pre>`,
  exceedsHighlightLimit: (content: string) => content.length > 300_000,
}));

describe("CodeViewer", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("shows a sticky path header with the current file's path", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ path: "src/main.py", content: "def main(): pass" }),
    }) as unknown as typeof fetch;

    render(<CodeViewer repoId="r1" path="src/main.py" />);

    await waitFor(() => expect(screen.getByText("src/main.py")).toBeInTheDocument());
  });

  it("skips syntax highlighting and shows a fallback for a file over the size guard", async () => {
    const hugeContent = "x".repeat(300_001);
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ path: "vendor/bundle.js", content: hugeContent }),
    }) as unknown as typeof fetch;

    render(<CodeViewer repoId="r1" path="vendor/bundle.js" />);

    expect(await screen.findByText(/too large to preview with syntax highlighting/i)).toBeInTheDocument();
    // The path header (and copy button) should still be usable even in the fallback state.
    expect(screen.getByText("vendor/bundle.js")).toBeInTheDocument();
    expect(screen.getByLabelText("Copy file contents")).toBeInTheDocument();
  });

  it("copies the file's content and shows a checkmark", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ path: "src/main.py", content: "def main(): pass" }),
    }) as unknown as typeof fetch;
    Object.assign(navigator, { clipboard: { writeText: jest.fn().mockResolvedValue(undefined) } });

    render(<CodeViewer repoId="r1" path="src/main.py" />);
    const copyButton = await screen.findByLabelText("Copy file contents");

    await userEvent.click(copyButton);

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("def main(): pass");
    expect(await screen.findByLabelText("Copied")).toBeInTheDocument();
  });
});
