"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Activity, Loader2 } from "lucide-react";
import { apiFetch } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { HealthScoreResponse } from "@/lib/types";

type Status = "idle" | "loading" | "success" | "error";

function scoreColor(score: number): string {
  if (score >= 80) return "text-emerald-400";
  if (score >= 50) return "text-amber-400";
  return "text-destructive";
}

function barColor(score: number): string {
  if (score >= 80) return "bg-emerald-400";
  if (score >= 50) return "bg-amber-400";
  return "bg-destructive";
}

export function HealthScorecard({ repoId }: { repoId: string }) {
  const [status, setStatus] = useState<Status>("idle");
  const [score, setScore] = useState<HealthScoreResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function compute() {
    setStatus("loading");
    setError(null);
    try {
      const res = await apiFetch(`/api/repos/${repoId}/health-score`, { cache: "no-store" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: undefined }));
        setError(body.detail ?? "Could not compute the score.");
        setStatus("error");
        return;
      }
      const data = (await res.json()) as HealthScoreResponse;
      setScore(data);
      setStatus("success");
    } catch {
      setError("Could not reach the server.");
      setStatus("error");
    }
  }

  if (status === "idle") {
    return (
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <Activity className="h-8 w-8 text-primary" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">Get a 0-100 code health &amp; maintainability score for this repo.</p>
        <Button onClick={compute}>Compute Score</Button>
      </div>
    );
  }

  if (status === "loading") {
    return (
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <motion.span animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: "linear" }}>
          <Loader2 className="h-6 w-6 text-primary" aria-hidden="true" />
        </motion.span>
        <p className="text-sm text-muted-foreground">
          Assessing documentation, tests, automation, and code quality...
        </p>
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

  if (!score) return null;

  const subEntries: [string, number][] = [
    ["Documentation", score.sub_scores.documentation],
    ["Testing", score.sub_scores.testing],
    ["Automation", score.sub_scores.automation],
    ["Code Quality", score.sub_scores.quality],
  ];

  return (
    <div className="space-y-4 p-3">
      <div className="flex flex-col items-center gap-1 py-2">
        <span className={cn("text-5xl font-bold tabular-nums", scoreColor(score.overall_score))}>
          {score.overall_score}
        </span>
        <span className="text-xs uppercase tracking-wide text-muted-foreground">Overall Score</span>
      </div>
      <div className="space-y-2.5">
        {subEntries.map(([label, value]) => (
          <div key={label}>
            <div className="mb-1 flex items-center justify-between text-xs">
              <span className="text-muted-foreground">{label}</span>
              <span className={cn("font-mono font-semibold", scoreColor(value))}>{value}</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-muted">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${value}%` }}
                transition={{ duration: 0.5, ease: "easeOut" }}
                className={cn("h-full rounded-full", barColor(value))}
              />
            </div>
          </div>
        ))}
      </div>
      <p className="glass rounded-md p-3 text-xs leading-relaxed text-zinc-300">{score.commentary}</p>
    </div>
  );
}
