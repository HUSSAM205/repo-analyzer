"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, Loader2, ShieldCheck } from "lucide-react";
import { apiFetch } from "@/lib/api-client";
import { downloadTextFile } from "@/lib/export-utils";
import { complianceToMarkdown } from "@/lib/report-formatters";
import { cn } from "@/lib/utils";
import type { ComplianceScanResponse } from "@/lib/types";
import { ExportMenu } from "./export-menu";

type Status = "idle" | "loading" | "success" | "error";

const RISK_STYLES: Record<string, string> = {
  low: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  medium: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  high: "border-destructive/40 bg-destructive/10 text-destructive",
  unknown: "border-zinc-700 bg-zinc-800/40 text-zinc-400",
};

export function CompliancePanel({ repoId }: { repoId: string }) {
  const [status, setStatus] = useState<Status>("idle");
  const [scan, setScan] = useState<ComplianceScanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Unlike the other flagship tools, this one is deterministic (no LLM
  // generation delay), so it fetches automatically on mount rather than
  // waiting for an explicit "start" click.
  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    setError(null);

    apiFetch(`/api/repos/${repoId}/compliance-scan`, { cache: "no-store" })
      .then(async (res) => {
        if (cancelled) return;
        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: undefined }));
          setError(body.detail ?? "Could not run the compliance scan.");
          setStatus("error");
          return;
        }
        const data = (await res.json()) as ComplianceScanResponse;
        // The backend's response schema defaults this field to [] (see
        // ComplianceScanResponse in schemas/flagship.py), but that only
        // covers the backend's own Pydantic serialization -- it doesn't
        // help if this frontend has already been redeployed while the
        // backend (a separately-deployed Render service, redeployed on its
        // own schedule from the same push) briefly still serves the older
        // shape. Confirmed live: that exact window produced a full
        // "Cannot read properties of undefined" crash here. Normalizing at
        // the one point data enters state, rather than scattering `?? []`
        // through the JSX below, keeps every read below able to assume the
        // array always exists.
        setScan({ ...data, dangerous_pattern_findings: data.dangerous_pattern_findings ?? [] });
        setStatus("success");
      })
      .catch(() => {
        if (!cancelled) {
          setError("Could not reach the server.");
          setStatus("error");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [repoId]);

  if (status === "idle" || status === "loading") {
    return (
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <motion.span animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: "linear" }}>
          <Loader2 className="h-6 w-6 text-primary" aria-hidden="true" />
        </motion.span>
        <p className="text-sm text-muted-foreground">Scanning dependencies and file contents...</p>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <p className="text-sm text-destructive">{error}</p>
      </div>
    );
  }

  if (!scan) return null;

  return (
    <div className="space-y-4 p-3">
      <div className="flex justify-end">
        <ExportMenu
          options={[
            {
              label: "Markdown",
              onSelect: () => downloadTextFile(complianceToMarkdown(scan), "security-report.md", "text/markdown"),
            },
            {
              label: "JSON",
              onSelect: () => downloadTextFile(JSON.stringify(scan, null, 2), "security-report.json", "application/json"),
            },
          ]}
        />
      </div>
      <div className="glass flex items-center gap-3 rounded-md p-3">
        <span
          className={cn(
            "flex h-10 w-10 shrink-0 items-center justify-center rounded-full ring-1",
            RISK_STYLES[scan.overall_risk] ?? RISK_STYLES.unknown
          )}
        >
          {scan.overall_risk === "low" ? (
            <ShieldCheck className="h-5 w-5" aria-hidden="true" />
          ) : (
            <AlertTriangle className="h-5 w-5" aria-hidden="true" />
          )}
        </span>
        <div>
          <p className="text-sm font-semibold uppercase tracking-wide text-foreground">
            {scan.overall_risk} overall risk
          </p>
          <p className="text-xs text-muted-foreground">
            {scan.secret_findings.length} potential secret{scan.secret_findings.length === 1 ? "" : "s"} ·{" "}
            {scan.dangerous_pattern_findings.length} risky code pattern
            {scan.dangerous_pattern_findings.length === 1 ? "" : "s"} ·{" "}
            {scan.license_findings.length} dependenc{scan.license_findings.length === 1 ? "y" : "ies"} checked
          </p>
        </div>
      </div>

      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-primary/80">
          Dangerous code patterns
        </h3>
        {scan.dangerous_pattern_findings.length === 0 ? (
          <p className="rounded-md border border-zinc-800/60 p-3 text-sm text-muted-foreground">
            No known-risky calls (eval, shell=True, dangerouslySetInnerHTML, ...) found in scanned files.
          </p>
        ) : (
          <ul className="space-y-2">
            {scan.dangerous_pattern_findings.map((finding, i) => (
              <li key={i} className="glass rounded-md p-2.5 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-mono text-zinc-400">
                    {finding.file}:{finding.line}
                  </span>
                  <span
                    className={cn(
                      "glow-pill shrink-0 rounded-full border px-2 py-0.5 font-semibold",
                      RISK_STYLES[finding.severity] ?? RISK_STYLES.unknown
                    )}
                  >
                    {finding.pattern}
                  </span>
                </div>
                <p className="mt-1 font-mono text-zinc-300">{finding.snippet}</p>
                <p className="mt-1 text-zinc-500">{finding.rationale}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-primary/80">Secret leak detection</h3>
        {scan.secret_findings.length === 0 ? (
          <p className="rounded-md border border-zinc-800/60 p-3 text-sm text-muted-foreground">
            No likely secrets found in scanned files.
          </p>
        ) : (
          <ul className="space-y-2">
            {scan.secret_findings.map((finding, i) => (
              <li key={i} className="glass rounded-md p-2.5 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-mono text-zinc-400">
                    {finding.file}:{finding.line}
                  </span>
                  <span className="glow-pill shrink-0 rounded-full border border-destructive/40 bg-destructive/10 px-2 py-0.5 font-semibold text-destructive">
                    {finding.pattern}
                  </span>
                </div>
                <p className="mt-1 font-mono text-zinc-300">{finding.preview}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-primary/80">License risk</h3>
        {scan.license_findings.length === 0 ? (
          <p className="rounded-md border border-zinc-800/60 p-3 text-sm text-muted-foreground">
            No dependency manifest found to check.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {scan.license_findings.map((finding) => (
              <li
                key={`${finding.ecosystem}-${finding.package}`}
                className="flex items-center justify-between gap-2 rounded-md border border-zinc-800/60 px-2.5 py-1.5 text-xs"
              >
                <span className="truncate font-mono text-zinc-200">{finding.package}</span>
                <span className={cn("shrink-0 rounded-full border px-2 py-0.5 font-semibold", RISK_STYLES[finding.risk])}>
                  {finding.likely_license}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <p className="text-[11px] leading-relaxed text-zinc-500">{scan.disclaimer}</p>
    </div>
  );
}
