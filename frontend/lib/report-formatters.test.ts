import { complianceToMarkdown, routesToMarkdown, routesToOpenApi } from "./report-formatters";
import type { ComplianceScanResponse, RouteExplorerResponse } from "@/lib/types";

describe("complianceToMarkdown", () => {
  it("includes the overall risk and each finding section as a table", () => {
    const scan: ComplianceScanResponse = {
      overall_risk: "high",
      license_findings: [{ package: "pyqt5", ecosystem: "pypi", likely_license: "GPL-3.0", risk: "high", note: "" }],
      secret_findings: [{ file: "config.py", line: 3, pattern: "AWS Access Key ID", preview: "AKIA****MNOP" }],
      dangerous_pattern_findings: [
        { file: "app.py", line: 12, pattern: "eval()", severity: "high", rationale: "...", snippet: "eval(x)" },
      ],
      disclaimer: "Pattern-based, not audit-grade.",
    };

    const md = complianceToMarkdown(scan);

    expect(md).toContain("**Overall risk:** high");
    expect(md).toContain("| high | eval() | app.py | 12 |");
    expect(md).toContain("| AWS Access Key ID | config.py | 3 |");
    expect(md).toContain("| pyqt5 | GPL-3.0 | high |");
    expect(md).toContain("Pattern-based, not audit-grade.");
  });

  it("shows a clean 'not found' line for each empty section instead of an empty table", () => {
    const scan: ComplianceScanResponse = {
      overall_risk: "low",
      license_findings: [],
      secret_findings: [],
      dangerous_pattern_findings: [],
      disclaimer: "...",
    };

    const md = complianceToMarkdown(scan);

    expect(md).toContain("No known-risky calls found.");
    expect(md).toContain("No likely secrets found.");
    expect(md).toContain("No dependency manifest found.");
  });
});

describe("routesToMarkdown", () => {
  it("renders each route as a table row with backtick-wrapped path", () => {
    const data: RouteExplorerResponse = {
      routes: [
        { method: "GET", path: "/api/v1/repos/{repo_id}", file: "repos.py", line: 10, framework: "fastapi", path_params: ["repo_id"], auth_required: true },
      ],
      frameworks_detected: ["fastapi"],
      disclaimer: "...",
    };

    const md = routesToMarkdown(data);

    expect(md).toContain("| GET | `/api/v1/repos/{repo_id}` | Required | repos.py:10 |");
  });

  it("marks a route with no auth as Open", () => {
    const data: RouteExplorerResponse = {
      routes: [{ method: "GET", path: "/health", file: "main.py", line: 1, framework: "fastapi", path_params: [], auth_required: false }],
      frameworks_detected: ["fastapi"],
      disclaimer: "...",
    };

    expect(routesToMarkdown(data)).toContain("Open");
  });
});

describe("routesToOpenApi", () => {
  it("produces a valid-shaped OpenAPI document with the route's method as the operation key", () => {
    const data: RouteExplorerResponse = {
      routes: [
        { method: "GET", path: "/api/v1/repos/{repo_id}", file: "repos.py", line: 10, framework: "fastapi", path_params: ["repo_id"], auth_required: true },
      ],
      frameworks_detected: ["fastapi"],
      disclaimer: "...",
    };

    const spec = JSON.parse(routesToOpenApi(data));

    expect(spec.openapi).toBe("3.0.0");
    expect(spec.paths["/api/v1/repos/{repo_id}"].get.parameters).toEqual([
      { name: "repo_id", in: "path", required: true, schema: { type: "string" } },
    ]);
    expect(spec.paths["/api/v1/repos/{repo_id}"].get.security).toEqual([{ bearerAuth: [] }]);
  });

  it("converts Express's :param syntax to OpenAPI's {param} syntax", () => {
    const data: RouteExplorerResponse = {
      routes: [
        { method: "POST", path: "/users/:userId/orders", file: "orders.js", line: 1, framework: "express", path_params: ["userId"], auth_required: false },
      ],
      frameworks_detected: ["express"],
      disclaimer: "...",
    };

    const spec = JSON.parse(routesToOpenApi(data));

    expect(spec.paths["/users/{userId}/orders"]).toBeDefined();
    expect(spec.paths["/users/:userId/orders"]).toBeUndefined();
  });

  it("groups multiple methods on the same path under one path entry", () => {
    const data: RouteExplorerResponse = {
      routes: [
        { method: "GET", path: "/api/repos/{id}", file: "route.ts", line: 1, framework: "nextjs", path_params: ["id"], auth_required: false },
        { method: "POST", path: "/api/repos/{id}", file: "route.ts", line: 8, framework: "nextjs", path_params: ["id"], auth_required: false },
      ],
      frameworks_detected: ["nextjs"],
      disclaimer: "...",
    };

    const spec = JSON.parse(routesToOpenApi(data));

    expect(Object.keys(spec.paths)).toEqual(["/api/repos/{id}"]);
    expect(spec.paths["/api/repos/{id}"].get).toBeDefined();
    expect(spec.paths["/api/repos/{id}"].post).toBeDefined();
  });

  it("omits parameters and security when there are none, rather than empty arrays", () => {
    const data: RouteExplorerResponse = {
      routes: [{ method: "GET", path: "/health", file: "main.py", line: 1, framework: "fastapi", path_params: [], auth_required: false }],
      frameworks_detected: ["fastapi"],
      disclaimer: "...",
    };

    const spec = JSON.parse(routesToOpenApi(data));

    expect(spec.paths["/health"].get.parameters).toBeUndefined();
    expect(spec.paths["/health"].get.security).toBeUndefined();
  });
});
