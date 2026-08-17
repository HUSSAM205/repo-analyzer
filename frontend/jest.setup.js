import "@testing-library/jest-dom";

// Route Handler tests (app/api/**/route.test.ts) opt into the "node" test
// environment via a `@jest-environment node` docblock, since jsdom doesn't
// provide the global Request/Response/fetch classes `next/server` needs --
// and a plain node environment has no `window`. Guard the jsdom-only setup
// below so this file still works as setupFilesAfterEach for those tests too.
if (typeof window !== "undefined") {
  // jsdom doesn't implement Element.scrollIntoView (it's a layout API jsdom has no
  // layout engine for). chat-panel.tsx's auto-scroll effect calls it unconditionally
  // whenever messages/streamingText change, so any test that renders ChatPanel --
  // even indirectly, e.g. RepoWorkspacePage's tests, which don't mock it -- hits
  // "scrollIntoView is not a function" unless it's stubbed here.
  window.HTMLElement.prototype.scrollIntoView = jest.fn();

  // jsdom has no ResizeObserver either. @radix-ui/react-scroll-area's
  // Scrollbar mounts one (to measure viewport/content size for the thumb) as
  // soon as a pointer interaction happens anywhere inside the ScrollArea --
  // real mouse/touch events, not the synthetic DOM events fired directly by
  // `fireEvent`. Only tests that click through `userEvent` inside a
  // ScrollArea (e.g. clicking chat-panel's "Retry" button) exercise that
  // path, so it wasn't needed until now.
  window.ResizeObserver =
    window.ResizeObserver ??
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
}
