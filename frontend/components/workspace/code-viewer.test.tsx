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

describe("CodeViewer Raw Code / Annotated View toggle", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  const CONTENT = "line1\nline2\nline3\nline4\nline5";

  function mockFetch(annotationsImpl: (call: number) => Promise<Response>) {
    let contentCalls = 0;
    let annotationsCalls = 0;
    const fn = jest.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/files/content")) {
        contentCalls += 1;
        return Promise.resolve({
          ok: true,
          json: async () => ({ path: "src/main.py", content: CONTENT }),
        } as Response);
      }
      if (url.includes("/files/annotations")) {
        annotationsCalls += 1;
        return annotationsImpl(annotationsCalls);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    }) as unknown as typeof fetch;
    global.fetch = fn;
    return {
      getContentCalls: () => contentCalls,
      getAnnotationsCalls: () => annotationsCalls,
    };
  }

  it("defaults to Raw Code with both toggle options rendered", async () => {
    mockFetch(() => Promise.reject(new Error("should not be called")));

    render(<CodeViewer repoId="r1" path="src/main.py" />);

    const rawTab = await screen.findByRole("tab", { name: "Raw Code" });
    const annotatedTab = await screen.findByRole("tab", { name: "Annotated View" });
    expect(rawTab).toHaveAttribute("aria-selected", "true");
    expect(annotatedTab).toHaveAttribute("aria-selected", "false");
  });

  it("shows an 'AI is analyzing' loading state while annotations are being fetched", async () => {
    mockFetch(() => new Promise(() => {})); // never resolves -- stays "loading"

    render(<CodeViewer repoId="r1" path="src/main.py" />);
    const annotatedTab = await screen.findByRole("tab", { name: "Annotated View" });

    await userEvent.click(annotatedTab);

    expect(await screen.findByText(/AI is analyzing this file/i)).toBeInTheDocument();
  });

  it("renders blocks with category badges and AI card fields on success, and switches back to Raw Code instantly with no re-fetch", async () => {
    const { getContentCalls, getAnnotationsCalls } = mockFetch((call) =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({
          path: "src/main.py",
          blocks: [
            {
              category: "imports",
              start_line: 1,
              end_line: 2,
              logic_summary: "Pulls in dependencies",
              flow: "Runs before anything else",
              tips: "Keep this list tidy",
            },
            {
              category: "business_logic",
              start_line: 3,
              end_line: 5,
              logic_summary: "Implements the core rule",
              flow: "Called from the handler below",
              tips: "Covered by unit tests",
            },
          ],
        }),
      } as unknown as Response)
    );

    render(<CodeViewer repoId="r1" path="src/main.py" />);
    const annotatedTab = await screen.findByRole("tab", { name: "Annotated View" });
    await userEvent.click(annotatedTab);

    expect(await screen.findByText("Imports")).toBeInTheDocument();
    expect(screen.getByText("Business Logic")).toBeInTheDocument();
    expect(screen.getByText("Pulls in dependencies")).toBeInTheDocument();
    expect(screen.getByText("Runs before anything else")).toBeInTheDocument();
    expect(screen.getByText("Keep this list tidy")).toBeInTheDocument();
    expect(screen.getByText("Implements the core rule")).toBeInTheDocument();

    expect(getContentCalls()).toBe(1);
    expect(getAnnotationsCalls()).toBe(1);

    const rawTab = screen.getByRole("tab", { name: "Raw Code" });
    await userEvent.click(rawTab);

    expect(screen.getByText("src/main.py")).toBeInTheDocument();
    expect(screen.queryByText("Imports")).not.toBeInTheDocument();
    // Switching back to Raw Code must be instant -- the already-fetched
    // content is reused, not re-fetched.
    expect(getContentCalls()).toBe(1);

    // Switching to Annotated View again must also not re-fetch -- the
    // already-fetched annotations are cached in memory.
    await userEvent.click(screen.getByRole("tab", { name: "Annotated View" }));
    expect(await screen.findByText("Imports")).toBeInTheDocument();
    expect(getAnnotationsCalls()).toBe(1);
  });

  it("shows a distinct 'too large to annotate' state on a 413, with the backend's detail message", async () => {
    mockFetch(() =>
      Promise.resolve({
        ok: false,
        status: 413,
        json: async () => ({ detail: "This file has 4,200 lines -- too large to annotate." }),
      } as unknown as Response)
    );

    render(<CodeViewer repoId="r1" path="src/main.py" />);
    await userEvent.click(await screen.findByRole("tab", { name: "Annotated View" }));

    expect(await screen.findByText("This file has 4,200 lines -- too large to annotate.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  const HANDLER_BLOCK_RESPONSE = {
    ok: true,
    status: 200,
    json: async () => ({
      path: "src/main.py",
      blocks: [
        {
          category: "handlers_endpoints",
          start_line: 1,
          end_line: 2,
          logic_summary: "Handles the request",
          flow: "Dispatched by the router",
          tips: "Validate input first",
        },
      ],
    }),
  } as unknown as Response;

  function make503(detail: string) {
    return Promise.resolve({
      ok: false,
      status: 503,
      json: async () => ({ detail }),
    } as unknown as Response);
  }

  it("automatically retries and recovers silently from a single transient 503 (no manual click needed)", async () => {
    const { getAnnotationsCalls } = mockFetch((call) =>
      call === 1 ? make503("AI annotation is temporarily unavailable. Try again shortly.") : Promise.resolve(HANDLER_BLOCK_RESPONSE)
    );

    render(<CodeViewer repoId="r1" path="src/main.py" />);
    await userEvent.click(await screen.findByRole("tab", { name: "Annotated View" }));

    // The automatic retry has a real ~1.5s delay -- give findByText enough
    // headroom to observe it without the test controlling time.
    expect(await screen.findByText("Handlers & Endpoints", {}, { timeout: 4000 })).toBeInTheDocument();
    expect(getAnnotationsCalls()).toBe(2);
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  }, 10000);

  it("falls back to the manual Retry button once automatic retries are exhausted on a persistent 503", async () => {
    const { getAnnotationsCalls } = mockFetch((call) =>
      call <= 2
        ? make503("AI annotation is temporarily unavailable. Try again shortly.")
        : Promise.resolve(HANDLER_BLOCK_RESPONSE)
    );

    render(<CodeViewer repoId="r1" path="src/main.py" />);
    await userEvent.click(await screen.findByRole("tab", { name: "Annotated View" }));

    expect(
      await screen.findByText("AI annotation is temporarily unavailable. Try again shortly.", {}, { timeout: 4000 })
    ).toBeInTheDocument();
    expect(getAnnotationsCalls()).toBe(2);
    const retryButton = screen.getByRole("button", { name: "Retry" });

    await userEvent.click(retryButton);

    expect(await screen.findByText("Handlers & Endpoints")).toBeInTheDocument();
    expect(getAnnotationsCalls()).toBe(3);
  }, 10000);

  it("shows a generic 'could not load annotations' message on a 404", async () => {
    mockFetch(() =>
      Promise.resolve({
        ok: false,
        status: 404,
        json: async () => ({ detail: "File not found" }),
      } as unknown as Response)
    );

    render(<CodeViewer repoId="r1" path="src/main.py" />);
    await userEvent.click(await screen.findByRole("tab", { name: "Annotated View" }));

    expect(await screen.findByText(/could not load annotations/i)).toBeInTheDocument();
  });
});
