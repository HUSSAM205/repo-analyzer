import { render, screen, waitFor } from "@testing-library/react";
import SettingsPage from "./page";

describe("SettingsPage", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("shows the theme toggle", () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => null }) as unknown as typeof fetch;
    render(<SettingsPage />);
    expect(screen.getByRole("button", { name: /switch to (light|dark) mode/i })).toBeInTheDocument();
  });

  it("shows guest account details once loaded", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "u1", email: null, created_at: "2026-01-15T00:00:00Z", is_guest: true }),
    }) as unknown as typeof fetch;

    render(<SettingsPage />);

    await waitFor(() => expect(screen.getByText("Guest")).toBeInTheDocument());
    expect(screen.queryByText(/email:/i)).not.toBeInTheDocument();
  });

  it("shows a registered account's email", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "u1", email: "a@b.com", created_at: "2026-01-15T00:00:00Z", is_guest: false }),
    }) as unknown as typeof fetch;

    render(<SettingsPage />);

    await waitFor(() => expect(screen.getByText("Registered")).toBeInTheDocument());
    expect(screen.getByText("a@b.com")).toBeInTheDocument();
  });

  it("shows an error state when the account details can't be loaded", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false }) as unknown as typeof fetch;

    render(<SettingsPage />);

    expect(await screen.findByText(/could not load your account details/i)).toBeInTheDocument();
  });
});
