import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CodeViewer } from "./code-viewer";

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
