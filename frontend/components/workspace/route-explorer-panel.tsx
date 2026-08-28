"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Loader2, Lock, Unlock } from "lucide-react";
import { apiFetch } from "@/lib/api-client";
import { downloadTextFile } from "@/lib/export-utils";
import { routesToMarkdown, routesToOpenApi } from "@/lib/report-formatters";
import { cn } from "@/lib/utils";
import type { RouteExplorerResponse } from "@/lib/types";
import { ExportMenu } from "./export-menu";

type Status = "idle" | "loading" | "success" | "error";

const METHOD_STYLES: Record<string, string> = {
  GET: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  POST: "border-blue-500/40 bg-blue-500/10 text-blue-300",
  PUT: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  PATCH: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  DELETE: "border-destructive/40 bg-destructive/10 text-destructive",
};
const DEFAULT_METHOD_STYLE = "border-zinc-700 bg-zinc-800/40 text-zinc-300";

export function RouteExplorerPanel({ repoId }: { repoId: string }) {
  const [status, setStatus] = useState<Status>("idle");
  const [data, setData] = useState<RouteExplorerResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [frameworkFilter, setFrameworkFilter] = useState<string | null>(null);

  // Deterministic (no LLM generation delay), same as CompliancePanel -- so
  // this fetches automatically on mount rather than waiting on a "start"
  // click that would just add a pointless extra step for an instant result.
  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    setError(null);

    apiFetch(`/api/repos/${repoId}/routes`, { cache: "no-store" })
      .then(async (res) => {
        if (cancelled) return;
        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: undefined }));
          setError(body.detail ?? "Could not extract routes.");
          setStatus("error");
          return;
        }
        const json = (await res.json()) as RouteExplorerResponse;
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
        <p className="text-sm text-muted-foreground">Scanning for API routes...</p>
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

  const visibleRoutes = frameworkFilter ? data.routes.filter((r) => r.framework === frameworkFilter) : data.routes;

  return (
    <div className="space-y-3 p-3">
      {data.routes.length === 0 ? (
        <p className="rounded-md border border-zinc-800/60 p-3 text-sm text-muted-foreground">
          No FastAPI, Express, or Next.js App Router routes were recognized in this repo.
        </p>
      ) : (
        <>
          <div className="flex justify-end">
            <ExportMenu
              options={[
                { label: "Markdown", onSelect: () => downloadTextFile(routesToMarkdown(data), "api-routes.md", "text/markdown") },
                { label: "OpenAPI (JSON)", onSelect: () => downloadTextFile(routesToOpenApi(data), "openapi.json", "application/json") },
              ]}
            />
          </div>
          {data.frameworks_detected.length > 1 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <button
                type="button"
                onClick={() => setFrameworkFilter(null)}
                className={cn(
                  "rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize transition-colors",
                  frameworkFilter === null ? "border-primary/50 bg-primary/10 text-primary" : "border-zinc-800/60 text-muted-foreground hover:text-foreground"
                )}
              >
                All
              </button>
              {data.frameworks_detected.map((fw) => (
                <button
                  key={fw}
                  type="button"
                  onClick={() => setFrameworkFilter(fw)}
                  className={cn(
                    "rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize transition-colors",
                    frameworkFilter === fw ? "border-primary/50 bg-primary/10 text-primary" : "border-zinc-800/60 text-muted-foreground hover:text-foreground"
                  )}
                >
                  {fw}
                </button>
              ))}
            </div>
          )}

          <div className="overflow-x-auto rounded-md border border-zinc-800/60">
            <table className="w-full min-w-[420px] text-left text-xs">
              <thead className="border-b border-zinc-800/60 text-muted-foreground">
                <tr>
                  <th className="px-2.5 py-2 font-medium">Method</th>
                  <th className="px-2.5 py-2 font-medium">Path</th>
                  <th className="px-2.5 py-2 font-medium">Auth</th>
                  <th className="px-2.5 py-2 font-medium">File</th>
                </tr>
              </thead>
              <tbody>
                {visibleRoutes.map((route, i) => (
                  <tr key={`${route.file}:${route.line}:${i}`} className="border-b border-zinc-800/40 last:border-0">
                    <td className="px-2.5 py-2">
                      <span
                        className={cn(
                          "glow-pill rounded-full border px-2 py-0.5 font-mono font-semibold",
                          METHOD_STYLES[route.method] ?? DEFAULT_METHOD_STYLE
                        )}
                      >
                        {route.method}
                      </span>
                    </td>
                    <td className="px-2.5 py-2 font-mono text-zinc-200">{route.path}</td>
                    <td className="px-2.5 py-2">
                      {route.auth_required ? (
                        <span className="flex items-center gap-1 text-amber-300" title="Heuristic -- see disclaimer">
                          <Lock className="h-3 w-3" aria-hidden="true" /> Required
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-muted-foreground">
                          <Unlock className="h-3 w-3" aria-hidden="true" /> Open
                        </span>
                      )}
                    </td>
                    <td className="px-2.5 py-2 truncate font-mono text-zinc-500">
                      {route.file}:{route.line}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <p className="text-[11px] leading-relaxed text-zinc-500">{data.disclaimer}</p>
    </div>
  );
}
