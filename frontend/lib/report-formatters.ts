import type { ComplianceScanResponse, RouteExplorerResponse } from "@/lib/types";

export function complianceToMarkdown(scan: ComplianceScanResponse): string {
  const lines: string[] = ["# Security & Compliance Report", "", `**Overall risk:** ${scan.overall_risk}`, ""];

  lines.push("## Dangerous Code Patterns", "");
  if (scan.dangerous_pattern_findings.length === 0) {
    lines.push("No known-risky calls found.", "");
  } else {
    lines.push("| Severity | Pattern | File | Line |", "|---|---|---|---|");
    for (const f of scan.dangerous_pattern_findings) {
      lines.push(`| ${f.severity} | ${f.pattern} | ${f.file} | ${f.line} |`);
    }
    lines.push("");
  }

  lines.push("## Secret Leak Detection", "");
  if (scan.secret_findings.length === 0) {
    lines.push("No likely secrets found.", "");
  } else {
    lines.push("| Pattern | File | Line |", "|---|---|---|");
    for (const f of scan.secret_findings) {
      lines.push(`| ${f.pattern} | ${f.file} | ${f.line} |`);
    }
    lines.push("");
  }

  lines.push("## License Risk", "");
  if (scan.license_findings.length === 0) {
    lines.push("No dependency manifest found.", "");
  } else {
    lines.push("| Package | License | Risk |", "|---|---|---|");
    for (const f of scan.license_findings) {
      lines.push(`| ${f.package} | ${f.likely_license} | ${f.risk} |`);
    }
    lines.push("");
  }

  lines.push("---", "", scan.disclaimer);
  return lines.join("\n");
}

// OpenAPI's path-parameter syntax is `{name}` -- FastAPI and this app's own
// Next.js route extraction already emit that, but Express routes keep
// their source `:name` syntax verbatim (faithful to what's actually in the
// code, which the routes *table* should show) -- converted here only,
// since a raw `:name` segment isn't valid OpenAPI.
function toOpenApiPath(path: string): string {
  return path.replace(/:([A-Za-z_][A-Za-z0-9_]*)/g, "{$1}");
}

export function routesToMarkdown(data: RouteExplorerResponse): string {
  const lines = ["# API Routes", "", "| Method | Path | Auth | File |", "|---|---|---|---|"];
  for (const r of data.routes) {
    lines.push(`| ${r.method} | \`${r.path}\` | ${r.auth_required ? "Required" : "Open"} | ${r.file}:${r.line} |`);
  }
  lines.push("", data.disclaimer);
  return lines.join("\n");
}

export function routesToOpenApi(data: RouteExplorerResponse): string {
  const paths: Record<string, Record<string, unknown>> = {};
  for (const r of data.routes) {
    const path = toOpenApiPath(r.path);
    const existing = paths[path] ?? {};
    existing[r.method.toLowerCase()] = {
      summary: `${r.method} ${path}`,
      ...(r.path_params.length > 0
        ? { parameters: r.path_params.map((p) => ({ name: p, in: "path", required: true, schema: { type: "string" } })) }
        : {}),
      responses: { "200": { description: "OK" } },
      ...(r.auth_required ? { security: [{ bearerAuth: [] }] } : {}),
    };
    paths[path] = existing;
  }
  return JSON.stringify(
    {
      openapi: "3.0.0",
      info: { title: "Extracted API Routes", version: "1.0.0" },
      paths,
    },
    null,
    2
  );
}
