import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WorkspaceShell } from "./workspace-shell";

let mockSearchParams = new URLSearchParams();
jest.mock("next/navigation", () => ({
  useSearchParams: () => mockSearchParams,
}));

const LEFT_WIDTH_KEY = "workspace-shell:left-width";
const RIGHT_WIDTH_KEY = "workspace-shell:right-width";

function setViewportWidth(width: number) {
  Object.defineProperty(window, "innerWidth", { writable: true, configurable: true, value: width });
  // The resize listener triggers a chain of state updates -- wrap in `act`
  // so they flush before assertions run, the same way RTL's own event
  // helpers do internally.
  act(() => {
    window.dispatchEvent(new Event("resize"));
  });
}

function renderShell() {
  return render(
    <WorkspaceShell left={<div>left-content</div>} center={<div>center-content</div>} right={<div>right-content</div>} />
  );
}

beforeEach(() => {
  mockSearchParams = new URLSearchParams();
});

describe("WorkspaceShell wide layout (>= 1024px)", () => {
  const original = window.innerWidth;

  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    setViewportWidth(original);
  });

  it("shows all three panes side by side, with no tabs", () => {
    setViewportWidth(1280);
    renderShell();

    expect(screen.getByText("left-content")).toBeInTheDocument();
    expect(screen.getByText("center-content")).toBeInTheDocument();
    expect(screen.getByText("right-content")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });

  it("still lets the manual toggle buttons collapse and reopen each sidebar", async () => {
    setViewportWidth(1280);
    renderShell();

    await userEvent.click(screen.getByLabelText("Toggle chat panel"));
    await waitFor(() => expect(screen.queryByText("right-content")).not.toBeInTheDocument());

    await userEvent.click(screen.getByLabelText("Toggle chat panel"));
    expect(await screen.findByText("right-content")).toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("Toggle file tree"));
    await waitFor(() => expect(screen.queryByText("left-content")).not.toBeInTheDocument());
  });

  it("renders a resize handle between each pair of open panes", () => {
    setViewportWidth(1280);
    renderShell();

    expect(screen.getByLabelText("Resize file tree panel")).toBeInTheDocument();
    expect(screen.getByLabelText("Resize chat panel")).toBeInTheDocument();
  });

  it("does not render a pane's resize handle once that pane is collapsed", async () => {
    setViewportWidth(1280);
    renderShell();

    await userEvent.click(screen.getByLabelText("Toggle chat panel"));

    await waitFor(() => expect(screen.queryByLabelText("Resize chat panel")).not.toBeInTheDocument());
    expect(screen.getByLabelText("Resize file tree panel")).toBeInTheDocument();
  });

  it("dragging the left resize handle grows the left pane and persists the new width to localStorage", () => {
    setViewportWidth(1280);
    renderShell();

    const handle = screen.getByLabelText("Resize file tree panel");

    fireEvent.mouseDown(handle, { clientX: 280 });
    fireEvent.mouseMove(window, { clientX: 340 });
    fireEvent.mouseUp(window, { clientX: 340 });

    // The left pane's content wrapper is given an explicit inline width
    // that mirrors the live resize state (framer-motion's `animate` width
    // on the outer <aside> settles a frame later and isn't reliably
    // observable synchronously in jsdom).
    const leftContentWrapper = screen.getByText("left-content").parentElement as HTMLElement;
    expect(leftContentWrapper.style.width).toBe("340px");
    expect(window.localStorage.getItem(LEFT_WIDTH_KEY)).toBe("340");
  });

  it("dragging the right resize handle left (toward center) grows the right pane", () => {
    setViewportWidth(1280);
    renderShell();

    const handle = screen.getByLabelText("Resize chat panel");

    fireEvent.mouseDown(handle, { clientX: 900 });
    fireEvent.mouseMove(window, { clientX: 850 }); // dragged left by 50px
    fireEvent.mouseUp(window, { clientX: 850 });

    const rightContentWrapper = screen.getByText("right-content").parentElement as HTMLElement;
    expect(rightContentWrapper.style.width).toBe("430px"); // 380 default + 50
    expect(window.localStorage.getItem(RIGHT_WIDTH_KEY)).toBe("430");
  });

  it("clamps a drag past the configured max width instead of growing unbounded", () => {
    setViewportWidth(1280);
    renderShell();

    const handle = screen.getByLabelText("Resize file tree panel");

    fireEvent.mouseDown(handle, { clientX: 280 });
    fireEvent.mouseMove(window, { clientX: 280 + 1000 }); // far past the 450px max
    fireEvent.mouseUp(window, { clientX: 280 + 1000 });

    const leftContentWrapper = screen.getByText("left-content").parentElement as HTMLElement;
    expect(leftContentWrapper.style.width).toBe("450px");
  });

  it("clamps a drag past the configured min width instead of shrinking to nothing", () => {
    setViewportWidth(1280);
    renderShell();

    const handle = screen.getByLabelText("Resize file tree panel");

    fireEvent.mouseDown(handle, { clientX: 280 });
    fireEvent.mouseMove(window, { clientX: 280 - 1000 }); // far past the 200px min
    fireEvent.mouseUp(window, { clientX: 280 - 1000 });

    const leftContentWrapper = screen.getByText("left-content").parentElement as HTMLElement;
    expect(leftContentWrapper.style.width).toBe("200px");
  });

  it("hydrates a previously-persisted width from localStorage on mount", async () => {
    window.localStorage.setItem(LEFT_WIDTH_KEY, "360");
    setViewportWidth(1280);
    renderShell();

    await waitFor(() => {
      const leftContentWrapper = screen.getByText("left-content").parentElement as HTMLElement;
      expect(leftContentWrapper.style.width).toBe("360px");
    });
  });

  it("ignores a corrupt/non-numeric stored width and falls back to the default", async () => {
    window.localStorage.setItem(LEFT_WIDTH_KEY, "not-a-number");
    setViewportWidth(1280);
    renderShell();

    const leftContentWrapper = screen.getByText("left-content").parentElement as HTMLElement;
    expect(leftContentWrapper.style.width).toBe("280px");
  });
});

describe("WorkspaceShell narrow (tabbed) layout (< 1024px)", () => {
  const original = window.innerWidth;

  afterEach(() => {
    setViewportWidth(original);
  });

  it("renders a Files/Code/AI Assistant tablist and only the Files pane by default", () => {
    setViewportWidth(768);
    renderShell();

    const tablist = screen.getByRole("tablist", { name: /workspace view/i });
    expect(tablist).toBeInTheDocument();

    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual([
      expect.stringContaining("Files"),
      expect.stringContaining("Code"),
      expect.stringContaining("AI Assistant"),
    ]);

    expect(screen.getByText("left-content")).toBeInTheDocument();
    expect(screen.queryByText("center-content")).not.toBeInTheDocument();
    expect(screen.queryByText("right-content")).not.toBeInTheDocument();
  });

  it("opens straight into the chat pane when the URL carries ?tab=chat (the sidebar's AI Chatbot link)", () => {
    mockSearchParams = new URLSearchParams("tab=chat");
    setViewportWidth(768);
    renderShell();

    expect(screen.getByText("right-content")).toBeInTheDocument();
    expect(screen.queryByText("left-content")).not.toBeInTheDocument();
  });

  it("shows exactly one pane at a time and switches when a tab is clicked", async () => {
    setViewportWidth(768);
    renderShell();

    await userEvent.click(screen.getByRole("tab", { name: /code/i }));
    expect(screen.queryByText("left-content")).not.toBeInTheDocument();
    expect(screen.getByText("center-content")).toBeInTheDocument();
    expect(screen.queryByText("right-content")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: /ai assistant/i }));
    expect(screen.queryByText("center-content")).not.toBeInTheDocument();
    expect(screen.getByText("right-content")).toBeInTheDocument();
  });

  it("marks the active tab via aria-selected", async () => {
    setViewportWidth(768);
    renderShell();

    expect(screen.getByRole("tab", { name: /files/i })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /code/i })).toHaveAttribute("aria-selected", "false");

    await userEvent.click(screen.getByRole("tab", { name: /code/i }));

    expect(screen.getByRole("tab", { name: /files/i })).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("tab", { name: /code/i })).toHaveAttribute("aria-selected", "true");
  });

  it("renders no resize handles in the tabbed layout", () => {
    setViewportWidth(768);
    renderShell();

    expect(screen.queryByLabelText("Resize file tree panel")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Resize chat panel")).not.toBeInTheDocument();
    expect(screen.queryByRole("separator")).not.toBeInTheDocument();
  });

  it("renders the tabbed view at a 375px (phone-sized) viewport too", () => {
    setViewportWidth(375);
    renderShell();

    expect(screen.getByRole("tablist", { name: /workspace view/i })).toBeInTheDocument();
    expect(screen.queryByText("center-content")).not.toBeInTheDocument();
  });

  it("switches from the tabbed layout back to the 3-pane layout when the viewport widens past the breakpoint", async () => {
    setViewportWidth(800);
    renderShell();
    expect(screen.getByRole("tablist")).toBeInTheDocument();

    setViewportWidth(1280);

    await waitFor(() => expect(screen.queryByRole("tablist")).not.toBeInTheDocument());
    expect(screen.getByText("left-content")).toBeInTheDocument();
    expect(screen.getByText("center-content")).toBeInTheDocument();
    expect(screen.getByText("right-content")).toBeInTheDocument();
  });

  it("switches from the 3-pane layout to the tabbed layout when the viewport narrows past the breakpoint", async () => {
    setViewportWidth(1280);
    renderShell();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();

    setViewportWidth(800);

    await waitFor(() => expect(screen.getByRole("tablist")).toBeInTheDocument());
    expect(screen.queryByText("center-content")).not.toBeInTheDocument();
  });
});
