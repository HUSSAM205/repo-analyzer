import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SecurityScanner } from "./security-scanner";

describe("SecurityScanner", () => {
  it("runs the scan and renders findings", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        findings: [
          {
            severity: "high",
            category: "security",
            file: "app/auth.py",
            line: 42,
            title: "Hardcoded secret key",
            description: "The JWT secret is hardcoded.",
          },
        ],
      }),
    }) as unknown as typeof fetch;

    render(<SecurityScanner repoId="r1" />);
    await userEvent.click(screen.getByRole("button", { name: /run scan/i }));

    expect(await screen.findByText("Hardcoded secret key")).toBeInTheDocument();
    expect(screen.getByText("high")).toBeInTheDocument();
    expect(screen.getByText(/app\/auth\.py:42/)).toBeInTheDocument();
  });

  it("shows a clean-scan message when no findings are returned", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ findings: [] }),
    }) as unknown as typeof fetch;

    render(<SecurityScanner repoId="r1" />);
    await userEvent.click(screen.getByRole("button", { name: /run scan/i }));

    expect(await screen.findByText(/no notable bugs/i)).toBeInTheDocument();
  });

  it("shows the backend's error message on failure", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "Could not run the scan." }),
    }) as unknown as typeof fetch;

    render(<SecurityScanner repoId="r1" />);
    await userEvent.click(screen.getByRole("button", { name: /run scan/i }));

    expect(await screen.findByText("Could not run the scan.")).toBeInTheDocument();
  });
});
