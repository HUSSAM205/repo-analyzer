import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatMessage } from "./chat-message";

Object.assign(navigator, { clipboard: { writeText: jest.fn().mockResolvedValue(undefined) } });

// Real Shiki's WASM cold-start is CPU-intensive -- mock it out the same way
// code-viewer.test.tsx does, so these stay fast component-level tests. The
// mocked HTML is wrapped in a distinguishable marker so tests can assert
// the highlighted variant actually got swapped in.
jest.mock("../../lib/highlight", () => ({
  highlightCode: async (code: string, language: string) =>
    `<pre data-testid="highlighted" data-lang="${language}"><code>${code}</code></pre>`,
}));

describe("ChatMessage", () => {
  it("renders a user message as plain text", () => {
    render(<ChatMessage role="user" content="What does main.py do?" />);
    expect(screen.getByText("What does main.py do?")).toBeInTheDocument();
  });

  it("renders assistant markdown, including a fenced code block with a copy button", async () => {
    render(<ChatMessage role="assistant" content={"It defines `main()`.\n\n```python\ndef main():\n    pass\n```"} />);
    expect(screen.getByText(/It defines/)).toBeInTheDocument();
    const copyButton = screen.getByLabelText("Copy code");
    await userEvent.click(copyButton);
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("def main():\n    pass");
  });

  it("renders a copy button for a fenced code block with no language tag", async () => {
    render(<ChatMessage role="assistant" content={"Output:\n\n```\n$ npm test\nOK\n```"} />);
    expect(screen.getByText(/Output:/)).toBeInTheDocument();
    const copyButton = screen.getByLabelText("Copy code");
    await userEvent.click(copyButton);
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("$ npm test\nOK");
  });

  it("does not syntax-highlight a fenced code block with no language tag", async () => {
    render(<ChatMessage role="assistant" content={"Output:\n\n```\n$ npm test\nOK\n```"} />);
    await waitFor(() => expect(screen.getByText(/Output:/)).toBeInTheDocument());
    expect(screen.queryByTestId("highlighted")).not.toBeInTheDocument();
  });

  it("syntax-highlights a fenced code block with a language tag via lib/highlight", async () => {
    render(
      <ChatMessage role="assistant" content={"It defines `main()`.\n\n```python\ndef main():\n    pass\n```"} />
    );

    const highlighted = await screen.findByTestId("highlighted");
    expect(highlighted).toHaveAttribute("data-lang", "python");
    expect(highlighted).toHaveTextContent("def main():");

    // Copy button still copies the raw, un-highlighted text.
    const copyButton = screen.getByLabelText("Copy code");
    await userEvent.click(copyButton);
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("def main():\n    pass");
  });

  it("renders a valid file:line citation as a clickable pill and fires onCitationClick with the path stripped", async () => {
    const onCitationClick = jest.fn();
    render(
      <ChatMessage
        role="assistant"
        content="See `app/core/agent.py:12-18` for details."
        onCitationClick={onCitationClick}
      />
    );

    const citation = screen.getByRole("button", { name: /app\/core\/agent\.py:12-18/ });
    await userEvent.click(citation);

    expect(onCitationClick).toHaveBeenCalledWith("app/core/agent.py");
  });

  it("strips a single-line (no range) citation suffix before calling onCitationClick", async () => {
    const onCitationClick = jest.fn();
    render(
      <ChatMessage role="assistant" content="See `app/core/agent.py:12` for details." onCitationClick={onCitationClick} />
    );

    await userEvent.click(screen.getByRole("button", { name: /app\/core\/agent\.py:12/ }));

    expect(onCitationClick).toHaveBeenCalledWith("app/core/agent.py");
  });

  it("does not treat an ordinary inline code span as a citation", () => {
    const onCitationClick = jest.fn();
    render(<ChatMessage role="assistant" content="Call `main()` to start." onCitationClick={onCitationClick} />);

    expect(screen.queryByRole("button", { name: /main\(\)/ })).not.toBeInTheDocument();
    expect(screen.getByText("main()")).toBeInTheDocument();
  });

  describe("word-break / overflow", () => {
    const longToken =
      "https://example.com/some-org/an-extremely-long-repository-name-with-no-natural-wrap-point/blob/main/very/deeply/nested/path/handler.py";

    it("applies break-words to a user message bubble so a long unbroken token can't force horizontal scroll", () => {
      render(<ChatMessage role="user" content={longToken} />);
      const paragraph = screen.getByText(longToken);
      expect(paragraph).toHaveClass("break-words");
      // The bubble itself (the paragraph's parent) also needs the class --
      // it's the element that's actually width-bounded (`max-w-[90%]`) by
      // the chat panel; without break-words here too the browser has no
      // wrap point on the outer box either.
      expect(paragraph.parentElement).toHaveClass("break-words");
    });

    it("applies break-words to an assistant message's markdown container", () => {
      render(<ChatMessage role="assistant" content={`See ${longToken} for details.`} />);
      const bubble = screen.getByText(/See/).closest(".prose");
      expect(bubble).toHaveClass("break-words");
    });

    it("keeps the CodeBlock scrollable within its own bounds via max-w-full + overflow-x-auto, not the whole panel", async () => {
      render(<ChatMessage role="assistant" content={"```\n" + "x".repeat(300) + "\n```"} />);
      const codeContainer = (await screen.findByText(/x{50,}/)).closest("div.group");
      expect(codeContainer).toHaveClass("overflow-x-auto");
      expect(codeContainer).toHaveClass("max-w-full");
    });

    it("breaks a long citation pill so it wraps instead of overflowing", async () => {
      const longPath = "app/core/very/deeply/nested/module/path/some_extremely_long_handler_file_name.py";
      render(<ChatMessage role="assistant" content={`See \`${longPath}:12-18\` for details.`} />);
      const citation = screen.getByRole("button", { name: new RegExp(longPath.replace(/[/.]/g, "\\$&")) });
      expect(citation).toHaveClass("break-all");
    });
  });
});
