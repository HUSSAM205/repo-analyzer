"use client";

import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowDown, ArrowUp, GitCompare, Loader2, Minus, X } from "lucide-react";
import { apiFetch } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type { Repo, RepoCompareResponse, RepoMetrics } from "@/lib/types";

type Status = "picking" | "loading" | "success" | "error";

const RISK_STYLES: Record<string, string> = {
  low: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  medium: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  high: "border-destructive/40 bg-destructive/10 text-destructive",
  unknown: "border-zinc-700 bg-zinc-800/40 text-zinc-400",
};

// Some deltas are morally neutral (more files/LOC/routes isn't good or bad
// on its own) while others clearly aren't (more vulnerabilities, higher
// average complexity) -- `invert` marks the latter so a positive (Repo B
// higher) delta reads as a warning color instead of a neutral one.
function DeltaRibbon({
  label,
  value,
  decimals = 0,
  invert = false,
}: {
  label: string;
  value: number;
  decimals?: number;
  invert?: boolean;
}) {
  const isZero = Math.abs(value) < 10 ** -decimals / 2;
  const isPositive = value > 0;
  const tone = isZero
    ? "border-zinc-700 bg-zinc-800/40 text-zinc-400"
    : invert
      ? isPositive
        ? "border-destructive/40 bg-destructive/10 text-destructive"
        : "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
      : "border-sky-500/40 bg-sky-500/10 text-sky-300";
  const Icon = isZero ? Minus : isPositive ? ArrowUp : ArrowDown;
  const formatted = Math.abs(value).toFixed(decimals);

  return (
    <div className="flex items-center justify-between gap-2 rounded-md border border-zinc-800/60 px-2.5 py-1.5 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("glow-pill flex items-center gap-1 rounded-full border px-2 py-0.5 font-semibold", tone)}>
        <Icon className="h-3 w-3" aria-hidden="true" />
        {isZero ? "±0" : formatted}
      </span>
    </div>
  );
}

function topModuleEntries(breakdown: Record<string, number>, max = 5): [string, number][] {
  return Object.entries(breakdown)
    .sort((a, b) => b[1] - a[1])
    .slice(0, max);
}

function MetricsCard({ label, name, url, metrics }: { label: string; name: string; url: string; metrics: RepoMetrics }) {
  return (
    <div className="glass min-w-0 flex-1 space-y-3 rounded-lg border border-zinc-800/60 p-3">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wide text-primary/80">{label}</p>
        <a href={url} target="_blank" rel="noreferrer" className="truncate text-sm font-medium text-foreground hover:underline">
          {name}
        </a>
      </div>

      <span
        className={cn(
          "glow-pill inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide",
          RISK_STYLES[metrics.overall_risk] ?? RISK_STYLES.unknown
        )}
      >
        {metrics.overall_risk} risk
      </span>

      <dl className="grid grid-cols-2 gap-2 text-xs">
        <div>
          <dt className="text-muted-foreground">Files</dt>
          <dd className="font-mono text-foreground">{metrics.file_count}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Lines of code</dt>
          <dd className="font-mono text-foreground">{metrics.lines_of_code}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Avg. complexity</dt>
          <dd className="font-mono text-foreground">{metrics.average_complexity}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Functions analyzed</dt>
          <dd className="font-mono text-foreground">{metrics.functions_analyzed}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">API routes</dt>
          <dd className="font-mono text-foreground">{metrics.route_count}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Flagged findings</dt>
          <dd className="font-mono text-foreground">{metrics.vulnerability_count}</dd>
        </div>
      </dl>

      {metrics.frameworks_detected.length > 0 && (
        <p className="text-[11px] text-zinc-500">Frameworks: {metrics.frameworks_detected.join(", ")}</p>
      )}

      {Object.keys(metrics.module_breakdown).length > 0 && (
        <div>
          <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-zinc-500">Module breakdown</p>
          <ul className="space-y-1">
            {topModuleEntries(metrics.module_breakdown).map(([dir, count]) => (
              <li key={dir} className="flex items-center justify-between text-[11px]">
                <span className="truncate font-mono text-zinc-400">{dir}/</span>
                <span className="font-mono text-zinc-300">{count}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function RepoCompareModal({
  repoId,
  repoName,
  onClose,
}: {
  repoId: string;
  repoName: string;
  onClose: () => void;
}) {
  const [status, setStatus] = useState<Status>("picking");
  const [candidates, setCandidates] = useState<Repo[] | null>(null);
  const [repoBId, setRepoBId] = useState("");
  const [result, setResult] = useState<RepoCompareResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch("/api/repos", { cache: "no-store" })
      .then(async (res) => {
        if (!res.ok) {
          setCandidates([]);
          return;
        }
        const repos = (await res.json()) as Repo[];
        setCandidates(repos.filter((r) => r.status === "ready" && r.id !== repoId));
      })
      .catch(() => setCandidates([]));
  }, [repoId]);

  const readyCandidates = useMemo(() => candidates ?? [], [candidates]);

  async function runCompare() {
    if (!repoBId) return;
    setStatus("loading");
    setError(null);
    try {
      const res = await apiFetch(
        `/api/repos/compare?repo_a=${encodeURIComponent(repoId)}&repo_b=${encodeURIComponent(repoBId)}`,
        { cache: "no-store" }
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: undefined }));
        setError(body.detail ?? "Could not compare these repositories.");
        setStatus("error");
        return;
      }
      const data = (await res.json()) as RepoCompareResponse;
      setResult(data);
      setStatus("success");
    } catch {
      setError("Could not reach the server.");
      setStatus("error");
    }
  }

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.15 }}
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
        onClick={onClose}
      >
        <motion.div
          role="dialog"
          aria-modal="true"
          aria-label="Compare repositories"
          initial={{ opacity: 0, scale: 0.96, y: 8 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.96, y: 8 }}
          transition={{ duration: 0.18, ease: "easeOut" }}
          onClick={(e) => e.stopPropagation()}
          className="glass flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-border shadow-2xl"
        >
          <div className="flex shrink-0 items-center justify-between border-b border-border px-4 py-3">
            <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
              <GitCompare className="h-4 w-4 text-primary" aria-hidden="true" />
              Compare Repositories
            </span>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="rounded-md p-1 text-muted-foreground transition-colors hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto scrollbar-thin p-4">
            {(status === "picking" || status === "loading") && (
              <div className="space-y-3">
                <p className="text-xs text-muted-foreground">
                  Comparing <span className="font-mono text-foreground">{repoName}</span> (Repo A) against:
                </p>
                {candidates === null ? (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                    Loading your repositories...
                  </div>
                ) : readyCandidates.length === 0 ? (
                  <p className="rounded-md border border-zinc-800/60 p-3 text-sm text-muted-foreground">
                    No other analyzed repositories yet -- analyze a second repo to compare it against this one.
                  </p>
                ) : (
                  <>
                    <select
                      aria-label="Repo B"
                      value={repoBId}
                      onChange={(e) => setRepoBId(e.target.value)}
                      className="glass w-full rounded-md border border-zinc-800/60 px-3 py-2 text-sm text-foreground"
                    >
                      <option value="">Select a repository...</option>
                      {readyCandidates.map((r) => (
                        <option key={r.id} value={r.id}>
                          {r.name}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={runCompare}
                      disabled={!repoBId || status === "loading"}
                      className="glow-pill glass flex items-center gap-2 rounded-full px-4 py-2 text-xs font-medium text-foreground transition-colors hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {status === "loading" && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
                      Compare
                    </button>
                  </>
                )}
              </div>
            )}

            {status === "error" && (
              <div className="space-y-3">
                <p className="text-sm text-destructive">{error}</p>
                <button
                  type="button"
                  onClick={() => setStatus("picking")}
                  className="glass rounded-full px-4 py-2 text-xs font-medium text-foreground"
                >
                  Try again
                </button>
              </div>
            )}

            {status === "success" && result && (
              <div className="space-y-4">
                <div className="flex flex-col gap-3 sm:flex-row">
                  <MetricsCard label="Repo A" name={result.repo_a.name} url={result.repo_a.url} metrics={result.repo_a.metrics} />
                  <MetricsCard label="Repo B" name={result.repo_b.name} url={result.repo_b.url} metrics={result.repo_b.metrics} />
                </div>

                <div>
                  <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-primary/80">
                    Delta (Repo B vs Repo A)
                  </p>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                    <DeltaRibbon label="Files" value={result.deltas.file_count_delta} />
                    <DeltaRibbon label="Lines of code" value={result.deltas.lines_of_code_delta} />
                    <DeltaRibbon label="Avg. complexity" value={result.deltas.average_complexity_delta} decimals={1} invert />
                    <DeltaRibbon label="API routes" value={result.deltas.route_count_delta} />
                    <DeltaRibbon label="Flagged findings" value={result.deltas.vulnerability_count_delta} invert />
                  </div>
                </div>

                <div className="glass rounded-md border border-zinc-800/60 p-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-primary/80">Security verdict</p>
                  <p className="mt-1 text-sm text-foreground">{result.security_verdict}</p>
                </div>

                <p className="text-[11px] leading-relaxed text-zinc-500">{result.disclaimer}</p>

                <button
                  type="button"
                  onClick={() => {
                    setStatus("picking");
                    setResult(null);
                    setRepoBId("");
                  }}
                  className="glass rounded-full px-4 py-2 text-xs font-medium text-foreground"
                >
                  Compare another
                </button>
              </div>
            )}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
