"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Loader2 } from "lucide-react";
import { apiFetch } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type { ComplexityRadarResponse } from "@/lib/types";

type Status = "idle" | "loading" | "success" | "error";

function maintainabilityStyle(score: number): string {
  if (score >= 70) return "border-emerald-500/40 bg-emerald-500/10 text-emerald-300";
  if (score >= 40) return "border-amber-500/40 bg-amber-500/10 text-amber-300";
  return "border-destructive/40 bg-destructive/10 text-destructive";
}

export function ComplexityRadarPanel({ repoId }: { repoId: string }) {
  const [status, setStatus] = useState<Status>("idle");
  const [data, setData] = useState<ComplexityRadarResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Deterministic (a real but bounded tree-sitter parse, no LLM generation
  // delay) -- fetches automatically on mount, same reasoning as the other
  // zero-token flagship panels.
  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    setError(null);

    apiFetch(`/api/repos/${repoId}/complexity`, { cache: "no-store" })
      .then(async (res) => {
        if (cancelled) return;
        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: undefined }));
          setError(body.detail ?? "Could not analyze complexity.");
          setStatus("error");
          return;
        }
        const json = (await res.json()) as ComplexityRadarResponse;
        setData(json);
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
        <p className="text-sm text-muted-foreground">Parsing functions and scoring complexity...</p>
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

  if (!data) return null;

  return (
    <div className="space-y-3 p-3">
      <div className="glass flex items-center gap-4 rounded-md p-3 text-xs text-muted-foreground">
        <span>
          <span className="font-mono text-base font-semibold text-foreground">{data.functions_analyzed}</span> functions
          analyzed
        </span>
        <span>
          Average complexity <span className="font-mono text-foreground">{data.average_complexity}</span>
        </span>
      </div>

      {data.hotspots.length === 0 ? (
        <p className="rounded-md border border-zinc-800/60 p-3 text-sm text-muted-foreground">
          No Python/JS/TS functions found to analyze, or nothing complex enough to flag.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-md border border-zinc-800/60">
          <table className="w-full min-w-[420px] text-left text-xs">
            <thead className="border-b border-zinc-800/60 text-muted-foreground">
              <tr>
                <th className="px-2.5 py-2 font-medium">Function</th>
                <th className="px-2.5 py-2 font-medium">Complexity</th>
                <th className="px-2.5 py-2 font-medium">Maintainability</th>
                <th className="px-2.5 py-2 font-medium">Location</th>
              </tr>
            </thead>
            <tbody>
              {data.hotspots.map((hotspot, i) => (
                <tr key={`${hotspot.file}:${hotspot.line}:${i}`} className="border-b border-zinc-800/40 last:border-0">
                  <td className="px-2.5 py-2 font-mono text-zinc-200">{hotspot.function}</td>
                  <td className="px-2.5 py-2">
                    <span className="glow-pill rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 font-mono font-semibold text-primary">
                      {hotspot.complexity}
                    </span>
                  </td>
                  <td className="px-2.5 py-2">
                    <span className={cn("rounded-full border px-2 py-0.5 font-mono font-semibold", maintainabilityStyle(hotspot.maintainability))}>
                      {hotspot.maintainability}
                    </span>
                  </td>
                  <td className="px-2.5 py-2 truncate font-mono text-zinc-500">
                    {hotspot.file}:{hotspot.line}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-[11px] leading-relaxed text-zinc-500">{data.disclaimer}</p>
    </div>
  );
}
