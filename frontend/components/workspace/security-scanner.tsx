"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, Loader2, ShieldAlert } from "lucide-react";
import { apiFetch } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { SecurityFinding, SecurityScanResponse } from "@/lib/types";

type Status = "idle" | "loading" | "success" | "error";

const SEVERITY_STYLES: Record<SecurityFinding["severity"], string> = {
  critical: "border-red-500/40 bg-red-500/10 text-red-300",
  high: "border-orange-500/40 bg-orange-500/10 text-orange-300",
  medium: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  low: "border-sky-500/40 bg-sky-500/10 text-sky-300",
};

export function SecurityScanner({ repoId }: { repoId: string }) {
  const [status, setStatus] = useState<Status>("idle");
  const [findings, setFindings] = useState<SecurityFinding[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function scan() {
    setStatus("loading");
    setError(null);
    try {
      const res = await apiFetch(`/api/repos/${repoId}/security-scan`, { cache: "no-store" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: undefined }));
        setError(body.detail ?? "Could not run the scan.");
        setStatus("error");
        return;
      }
      const data = (await res.json()) as SecurityScanResponse;
      setFindings(data.findings);
      setStatus("success");
    } catch {
      setError("Could not reach the server.");
      setStatus("error");
    }
  }

  if (status === "idle") {
    return (
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <ShieldAlert className="h-8 w-8 text-primary" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">
          Scan this repo&apos;s code for bugs, anti-patterns, and security vulnerabilities.
        </p>
        <Button onClick={scan}>Run Scan</Button>
      </div>
    );
  }

  if (status === "loading") {
    return (
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <motion.span animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: "linear" }}>
          <Loader2 className="h-6 w-6 text-primary" aria-hidden="true" />
        </motion.span>
        <p className="text-sm text-muted-foreground">Reviewing source files for issues...</p>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <p className="text-sm text-destructive">{error}</p>
        <Button size="sm" variant="outline" onClick={scan}>
          Retry
        </Button>
      </div>
    );
  }

  if (findings.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 p-6 text-center">
        <p className="text-sm text-muted-foreground">
          No notable bugs, anti-patterns, or vulnerabilities found in the sampled files.
        </p>
      </div>
    );
  }

  return (
    <ul className="space-y-2 overflow-auto p-3">
      {findings.map((f, i) => (
        <motion.li
          key={`${f.file}-${f.line}-${i}`}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.15, delay: Math.min(i * 0.03, 0.3) }}
          className="glass rounded-md p-3"
        >
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                SEVERITY_STYLES[f.severity]
              )}
            >
              <AlertTriangle className="h-3 w-3" aria-hidden="true" />
              {f.severity}
            </span>
            <span className="font-mono text-[11px] text-zinc-500">
              {f.file}
              {f.line != null ? `:${f.line}` : ""}
            </span>
          </div>
          <p className="text-sm font-medium text-foreground">{f.title}</p>
          <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{f.description}</p>
        </motion.li>
      ))}
    </ul>
  );
}
