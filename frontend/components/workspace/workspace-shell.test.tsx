import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WorkspaceShell } from "./workspace-shell";

function setViewportWidth(width: number) {
  Object.defineProperty(window, "innerWidth", { writable: true, configurable: true, value: width });
  // The resize listener triggers a chain of two state updates (the width
  // hook re-renders, then the auto-collapse effect reacts to that new
  // value) -- wrap in `act` so both flush before assertions run, the same
  // way RTL's own event helpers do internally.
  act(() => {
    window.dispatchEvent(new Event("resize"));
  });
}

describe("WorkspaceShell responsive collapse", () => {
  const original = window.innerWidth;

  afterEach(() => {
    setViewportWidth(original);
  });

  it("keeps both sidebars open by default at a wide viewport", () => {
    setViewportWidth(1280);
    render(<WorkspaceShell left={<div>left-content</div>} center={<div>center-content</div>} right={<div>right-content</div>} />);

    expect(screen.getByText("left-content")).toBeInTheDocument();
    expect(screen.getByText("right-content")).toBeInTheDocument();
  });

  it("auto-collapses the right (chat) sidebar when the viewport narrows below ~1024px", async () => {
    setViewportWidth(1280);
    render(<WorkspaceShell left={<div>left-content</div>} center={<div>center-content</div>} right={<div>right-content</div>} />);

    expect(screen.getByText("right-content")).toBeInTheDocument();

    setViewportWidth(800);

    expect(await screen.findByLabelText("Toggle chat panel")).toBeInTheDocument();
    // framer-motion's AnimatePresence keeps the exiting <aside> mounted for
    // its exit transition (~200ms) before actually removing it -- wait for
    // that real-time animation to finish rather than asserting immediately.
    await waitFor(() => expect(screen.queryByText("right-content")).not.toBeInTheDocument());
  });

  it("still lets the manual toggle reopen the sidebar after an auto-collapse", async () => {
    setViewportWidth(800);
    render(<WorkspaceShell left={<div>left-content</div>} center={<div>center-content</div>} right={<div>right-content</div>} />);

    await waitFor(() => expect(screen.queryByText("right-content")).not.toBeInTheDocument());

    await userEvent.click(screen.getByLabelText("Toggle chat panel"));

    expect(await screen.findByText("right-content")).toBeInTheDocument();
  });
});
