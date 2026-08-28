import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CompliancePanel } from "./compliance-panel";

describe("CompliancePanel", () => {
  it("fetches automatically on mount and renders findings", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        overall_risk: "high",
        license_findings: [
          { package: "react", ecosystem: "npm", likely_license: "MIT", risk: "low", note: "Known." },
        ],
        secret_findings: [
          { file: "config.py", line: 3, pattern: "AWS Access Key ID", preview: "AKIA****MNOP" },
        ],
        dangerous_pattern_findings: [
          {
            file: "app.py",
            line: 12,
            pattern: "eval()",
            severity: "high",
            rationale: "Executes a string as code.",
            snippet: "result = eval(user_input)",
          },
        ],
        disclaimer: "Pattern-based, not a substitute for a real audit.",
      }),
    }) as unknown as typeof fetch;

    render(<CompliancePanel repoId="r1" />);

    expect(await screen.findByText(/high overall risk/i)).toBeInTheDocument();
    expect(screen.getByText("config.py:3")).toBeInTheDocument();
    expect(screen.getByText("AWS Access Key ID")).toBeInTheDocument();
    expect(screen.getByText("react")).toBeInTheDocument();
    expect(screen.getByText("app.py:12")).toBeInTheDocument();
    expect(screen.getByText("eval()")).toBeInTheDocument();
    expect(screen.getByText("result = eval(user_input)")).toBeInTheDocument();
  });

  it("shows a happy state when nothing is found", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        overall_risk: "low",
        license_findings: [],
        secret_findings: [],
        dangerous_pattern_findings: [],
        disclaimer: "Pattern-based, not a substitute for a real audit.",
      }),
    }) as unknown as typeof fetch;

    render(<CompliancePanel repoId="r1" />);

    expect(await screen.findByText(/no likely secrets found/i)).toBeInTheDocument();
    expect(screen.getByText(/no known-risky calls/i)).toBeInTheDocument();
    expect(screen.getByText(/no dependency manifest found/i)).toBeInTheDocument();
  });

  it("offers a Markdown/JSON export of the scan once it's loaded", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        overall_risk: "low",
        license_findings: [],
        secret_findings: [],
        dangerous_pattern_findings: [],
        disclaimer: "...",
      }),
    }) as unknown as typeof fetch;

    render(<CompliancePanel repoId="r1" />);
    await screen.findByText(/no likely secrets found/i);

    await userEvent.click(screen.getByRole("button", { name: /export/i }));

    expect(screen.getByRole("menuitem", { name: "Markdown" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "JSON" })).toBeInTheDocument();
  });

  it("does not crash when the backend response has no dangerous_pattern_findings field", async () => {
    // Confirmed live: this exact shape (the field genuinely absent, not
    // just empty) crashed the panel with "Cannot read properties of
    // undefined (reading 'length')" during the deploy window where this
    // frontend had already redeployed but the separately-deployed backend
    // (Render, on its own schedule from the same push) still served the
    // pre-this-feature response shape. Old cached compliance_scan rows in
    // the DB will also legitimately omit this key forever until
    // re-analyzed, since that scan is cached permanently.
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        overall_risk: "low",
        license_findings: [],
        secret_findings: [],
        disclaimer: "Pattern-based, not a substitute for a real audit.",
      }),
    }) as unknown as typeof fetch;

    render(<CompliancePanel repoId="r1" />);

    expect(await screen.findByText(/no known-risky calls/i)).toBeInTheDocument();
  });

  it("shows the backend's error message on failure", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "This repository hasn't finished analyzing yet." }),
    }) as unknown as typeof fetch;

    render(<CompliancePanel repoId="r1" />);

    expect(await screen.findByText("This repository hasn't finished analyzing yet.")).toBeInTheDocument();
  });
});
