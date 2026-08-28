import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReadmeGenerator } from "./readme-generator";

describe("ReadmeGenerator", () => {
  it("generates and displays the README on click", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ content: "# Demo\n\nA demo project." }),
    }) as unknown as typeof fetch;

    render(<ReadmeGenerator repoId="r1" />);
    await userEvent.click(screen.getByRole("button", { name: /generate readme/i }));

    expect(await screen.findByText(/# Demo/)).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith("/api/repos/r1/readme", expect.objectContaining({ cache: "no-store" }));
  });

  it("shows the backend's error message and allows retrying on failure", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "The AI provider is temporarily unavailable. Please try again." }),
    }) as unknown as typeof fetch;

    render(<ReadmeGenerator repoId="r1" />);
    await userEvent.click(screen.getByRole("button", { name: /generate readme/i }));

    expect(await screen.findByText(/temporarily unavailable/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("copies the generated content to the clipboard", async () => {
    const writeText = jest.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ content: "# Demo" }),
    }) as unknown as typeof fetch;

    render(<ReadmeGenerator repoId="r1" />);
    await userEvent.click(screen.getByRole("button", { name: /generate readme/i }));
    await screen.findByText("# Demo");

    await userEvent.click(screen.getByRole("button", { name: /copy/i }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith("# Demo"));
  });
});
