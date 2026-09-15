import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PanelErrorBoundary } from "@/components/error-boundary";

function Bomb({ shouldThrow }: { shouldThrow: boolean }): JSX.Element {
  if (shouldThrow) throw new Error("boom");
  return <div>real panel content</div>;
}

// Owns the "does the child throw" flag as real React state in the parent,
// flipped via the boundary's own onReset callback -- both that state update
// and the boundary's internal setState({hasError: false}) fire
// synchronously inside the same click handler, so React 18 batches them
// into one render pass, and Bomb correctly sees the fresh `shouldThrow`
// value on the retried render. (A plain module-level flag mutated as a
// render side effect doesn't work here: React's error-recovery path can
// re-invoke a throwing render an extra time internally, which flips such a
// flag before the boundary has actually settled.)
function RetryHarness() {
  const [shouldThrow, setShouldThrow] = useState(true);
  return (
    <PanelErrorBoundary label="code viewer" onReset={() => setShouldThrow(false)}>
      <Bomb shouldThrow={shouldThrow} />
    </PanelErrorBoundary>
  );
}

describe("PanelErrorBoundary", () => {
  let consoleErrorSpy: jest.SpyInstance;

  beforeEach(() => {
    // React logs the thrown error to console.error itself during the
    // boundary's own render pass -- expected noise for this test, not a
    // real failure to surface.
    consoleErrorSpy = jest.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    consoleErrorSpy.mockRestore();
  });

  it("renders children normally when nothing throws", () => {
    render(
      <PanelErrorBoundary label="file tree">
        <Bomb shouldThrow={false} />
      </PanelErrorBoundary>
    );

    expect(screen.getByText("real panel content")).toBeInTheDocument();
  });

  it("shows an isolated fallback naming the panel when a child throws, instead of crashing the page", () => {
    render(
      <PanelErrorBoundary label="file tree">
        <Bomb shouldThrow={true} />
      </PanelErrorBoundary>
    );

    expect(screen.getByText("The file tree hit an error")).toBeInTheDocument();
    expect(screen.queryByText("real panel content")).not.toBeInTheDocument();
  });

  it("resets and re-attempts rendering the children when Retry is clicked", async () => {
    const user = userEvent.setup();

    render(<RetryHarness />);
    expect(screen.getByText("The code viewer hit an error")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(screen.getByText("real panel content")).toBeInTheDocument();
  });
});
