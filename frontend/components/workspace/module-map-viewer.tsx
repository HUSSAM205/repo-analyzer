"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Loader2 } from "lucide-react";
import { apiFetch } from "@/lib/api-client";
import type { ModuleMapResponse } from "@/lib/types";
import { DiagramExportMenu } from "./diagram-export-menu";

type Status = "idle" | "loading" | "success" | "error";

let mermaidIdCounter = 0;

export function ModuleMapViewer({ repoId }: { repoId: string }) {
  const [status, setStatus] = useState<Status>("idle");
  const [data, setData] = useState<ModuleMapResponse | null>(null);
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Deterministic (regex over file paths already loaded server-side, no
  // LLM generation delay) -- fetches automatically on mount, same reasoning
  // as CompliancePanel/RouteExplorerPanel.
  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    setError(null);
    setSvg(null);

    apiFetch(`/api/repos/${repoId}/module-map`, { cache: "no-store" })
      .then(async (res) => {
        if (cancelled) return;
        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: undefined }));
          setError(body.detail ?? "Could not generate the module map.");
          setStatus("error");
          return;
        }
        const json = (await res.json()) as ModuleMapResponse;
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

  // Same render-to-SVG approach as FlowMapViewer (see that component's own
  // comment for why this can't happen synchronously with the fetch above).
  useEffect(() => {
    if (!data?.diagram) return;
    let cancelled = false;

    import("mermaid").then(async ({ default: mermaid }) => {
      mermaid.initialize({ startOnLoad: false, theme: "dark", securityLevel: "strict" });
      mermaidIdCounter += 1;
      try {
        const { svg: rendered } = await mermaid.render(`module-map-${mermaidIdCounter}`, data.diagram);
        if (!cancelled) setSvg(rendered);
      } catch {
        if (!cancelled) {
          setError("The generated diagram could not be rendered.");
          setStatus("error");
        }
      }
    });

    return () => {
      cancelled = true;
    };
  }, [data]);

  if (status === "idle" || status === "loading" || (status === "success" && !svg)) {
    return (
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <motion.span animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: "linear" }}>
          <Loader2 className="h-6 w-6 text-primary" aria-hidden="true" />
        </motion.span>
        <p className="text-sm text-muted-foreground">Mapping the directory structure...</p>
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

  return (
    <div className="flex flex-1 flex-col overflow-auto p-4">
      {data && svg && (
        <div className="mb-3 flex items-center justify-between gap-3">
          <p className="text-xs text-muted-foreground">
            {data.file_count} files across {data.directory_count} top-level director{data.directory_count === 1 ? "y" : "ies"}
            -- purely structural, no AI involved.
          </p>
          <DiagramExportMenu diagram={data.diagram} svg={svg} filenamePrefix="module-map" />
        </div>
      )}
      <div
        role="img"
        aria-label="Repository directory/module structure diagram"
        className="mx-auto [&_.edgeLabel]:!bg-transparent [&_.node_rect]:[filter:drop-shadow(0_0_6px_hsl(var(--primary)/0.5))]"
        dangerouslySetInnerHTML={{ __html: svg ?? "" }}
      />
    </div>
  );
}
