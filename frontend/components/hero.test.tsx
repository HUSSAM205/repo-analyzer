import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Hero } from "./hero";

const push = jest.fn();
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh: jest.fn() }),
}));

// next-themes' useTheme() is safe to call without a provider (returns a
// no-op default context), but jsdom still needs window.matchMedia -- see
// jest.setup.js.
describe("Hero", () => {
  beforeEach(() => {
    push.mockClear();
  });

  it("renders the headline and quick-start demo buttons", () => {
    render(<Hero />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/understand any codebase/i);
    expect(screen.getByRole("button", { name: "facebook/react" })).toBeInTheDocument();
  });

  it("submits the URL for a clicked demo repo and navigates to its workspace", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ repo_id: "r1", job_id: "j1" }),
    }) as unknown as typeof fetch;

    render(<Hero />);
    await userEvent.click(screen.getByRole("button", { name: "pallets/flask" }));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        "/api/repos",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ repo_url: "https://github.com/pallets/flask" }),
        })
      );
    });
    await waitFor(() => expect(push).toHaveBeenCalledWith("/repos/r1?job=j1"));
  });
});
