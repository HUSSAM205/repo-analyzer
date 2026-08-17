import "@testing-library/jest-dom";

// jsdom doesn't implement Element.scrollIntoView (it's a layout API jsdom has no
// layout engine for). chat-panel.tsx's auto-scroll effect calls it unconditionally
// whenever messages/streamingText change, so any test that renders ChatPanel --
// even indirectly, e.g. RepoWorkspacePage's tests, which don't mock it -- hits
// "scrollIntoView is not a function" unless it's stubbed here.
window.HTMLElement.prototype.scrollIntoView = jest.fn();
