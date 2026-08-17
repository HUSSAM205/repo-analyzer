import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatMessage } from "./chat-message";

Object.assign(navigator, { clipboard: { writeText: jest.fn().mockResolvedValue(undefined) } });

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
});
