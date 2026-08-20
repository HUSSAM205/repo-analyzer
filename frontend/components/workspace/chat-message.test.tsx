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
});
