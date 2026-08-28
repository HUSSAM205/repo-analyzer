"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Clock, Loader2, Wrench } from "lucide-react";
import { apiFetch } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import type { TechDebtResponse } from "@/lib/types";

type Status = "idle" | "loading" | "success" | "error";

export function TechDebtPanel({ repoId }: { repoId: string }) {
  const [status, setStatus] = useState<Status>("idle");
  const [report, setReport] = useState<TechDebtResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function compute() {
    setStatus("loading");
    setError(null);
    try {
      const res = await apiFetch(`/api/repos/${repoId}/tech-debt`, { cache: "no-store" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: undefined }));
        setError(body.detail ?? "Could not generate the technical debt report.");
        setStatus("error");
        return;
      }
      const data = (await res.json()) as TechDebtResponse;
      setReport(data);
      setStatus("success");
    } catch {
      setError("Could not reach the server.");
      setStatus("error");
    }
  }

  if (status === "idle") {
    return (
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <Wrench className="h-8 w-8 text-primary" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">
          Estimate technical debt and get concrete before/after refactor recipes.
        </p>
        <Button onClick={compute}>Analyze Tech Debt</Button>
      </div>
    );
  }

  if (status === "loading") {
    return (
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <motion.span animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: "linear" }}>
          <Loader2 className="h-6 w-6 text-primary" aria-hidden="true" />
        </motion.span>
        <p className="text-sm text-muted-foreground">Estimating debt and drafting refactor recipes...</p>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <p className="text-sm text-destructive">{error}</p>
        <Button size="sm" variant="outline" onClick={compute}>
          Retry
        </Button>
      </div>
    );
  }

  if (!report) return null;

  return (
    <div className="space-y-4 p-3">
      <div className="glass flex items-center gap-3 rounded-md p-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary ring-1 ring-primary/30">
          <Clock className="h-5 w-5" aria-hidden="true" />
        </span>
        <div>
          <p className="text-2xl font-bold tabular-nums text-foreground">{report.estimated_debt_hours}h</p>
          <p className="text-xs uppercase tracking-wide text-muted-foreground">Estimated debt to pay down</p>
        </div>
      </div>

      <p className="text-sm leading-relaxed text-zinc-300">{report.summary}</p>

      {report.items.length === 0 ? (
        <p className="rounded-md border border-zinc-800/60 p-3 text-center text-sm text-muted-foreground">
          No significant technical debt found in the sampled files.
        </p>
      ) : (
        <div className="space-y-3">
          {report.items.map((item, i) => (
            <motion.div
              key={`${item.file}-${i}`}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, delay: Math.min(i * 0.03, 0.3) }}
              className="glass rounded-md p-3"
            >
              <div className="mb-1.5 flex items-center justify-between gap-2">
                <span className="truncate font-mono text-xs text-zinc-400">{item.file}</span>
                <span className="glow-pill shrink-0 rounded-full bg-amber-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-amber-300 ring-1 ring-amber-500/30">
                  ~{item.estimated_hours}h
                </span>
              </div>
              <p className="mb-2 text-sm font-medium text-foreground">{item.issue}</p>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <div>
                  <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-destructive/80">Before</p>
                  <pre className="overflow-x-auto rounded-md border border-destructive/20 bg-destructive/5 p-2 font-mono text-[11px] leading-relaxed text-zinc-300">
                    <code>{item.before_snippet}</code>
                  </pre>
                </div>
                <div>
                  <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-emerald-400/80">After</p>
                  <pre className="overflow-x-auto rounded-md border border-emerald-500/20 bg-emerald-500/5 p-2 font-mono text-[11px] leading-relaxed text-zinc-300">
                    <code>{item.after_snippet}</code>
                  </pre>
                </div>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-zinc-400">{item.explanation}</p>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}
