"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Loader2, Waypoints } from "lucide-react";
import { apiFetch } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import type { FlowMapResponse } from "@/lib/types";
import { DiagramExportMenu } from "./diagram-export-menu";

type Status = "idle" | "loading" | "success" | "error";

let mermaidIdCounter = 0;

export function FlowMapViewer({ repoId }: { repoId: string }) {
  const [status, setStatus] = useState<Status>("idle");
  const [diagram, setDiagram] = useState<string | null>(null);
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  async function start() {
    setStatus("loading");
    setError(null);
    try {
      const res = await apiFetch(`/api/repos/${repoId}/flow-map`, { cache: "no-store" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: undefined }));
        setError(body.detail ?? "Could not generate the architecture diagram.");
        setStatus("error");
        return;
      }
      const data = (await res.json()) as FlowMapResponse;
      setDiagram(data.diagram);
      setStatus("success");
    } catch {
      setError("Could not reach the server.");
      setStatus("error");
    }
  }

  // Renders the diagram text to SVG only once it's in hand -- mermaid's
  // render() is async and DOM-dependent, so this can't happen synchronously
  // during the fetch above. A fresh, incrementing id per render avoids
  // mermaid's own internal id collisions if this component re-renders more
  // than once in the same page session (e.g. switching repos).
  useEffect(() => {
    if (!diagram) return;
    let cancelled = false;

    import("mermaid").then(async ({ default: mermaid }) => {
      mermaid.initialize({ startOnLoad: false, theme: "dark", securityLevel: "strict" });
      mermaidIdCounter += 1;
      try {
        const { svg: rendered } = await mermaid.render(`flow-map-${mermaidIdCounter}`, diagram);
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
  }, [diagram]);

  if (status === "idle") {
    return (
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <Waypoints className="h-8 w-8 text-primary" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">
          Visualize this repo&apos;s request-handling architecture as a flow diagram.
        </p>
        <Button onClick={start}>Generate Flow Map</Button>
      </div>
    );
  }

  if (status === "loading" || (status === "success" && !svg)) {
    return (
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <motion.span animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: "linear" }}>
          <Loader2 className="h-6 w-6 text-primary" aria-hidden="true" />
        </motion.span>
        <p className="text-sm text-muted-foreground">Mapping the request-handling architecture...</p>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <p className="text-sm text-destructive">{error}</p>
        <Button size="sm" variant="outline" onClick={start}>
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col overflow-auto p-4">
      {diagram && svg && (
        <div className="mb-3 flex justify-end">
          <DiagramExportMenu diagram={diagram} svg={svg} filenamePrefix="architecture-flow" />
        </div>
      )}
      <div
        ref={containerRef}
        role="img"
        aria-label="Repository architecture flow diagram"
        // Nodes get a subtle glow so key architecture points read as "live"
        // rather than a flat static diagram -- purely a CSS treatment on
        // top of whatever mermaid renders, no per-node styling from the LLM
        // needed.
        className="mx-auto [&_.edgeLabel]:!bg-transparent [&_.node_circle]:[filter:drop-shadow(0_0_6px_hsl(var(--primary)/0.65))] [&_.node_polygon]:[filter:drop-shadow(0_0_6px_hsl(var(--primary)/0.65))] [&_.node_rect]:[filter:drop-shadow(0_0_6px_hsl(var(--primary)/0.65))]"
        dangerouslySetInnerHTML={{ __html: svg ?? "" }}
      />
    </div>
  );
}
