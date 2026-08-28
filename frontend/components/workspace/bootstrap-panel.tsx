"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Check, Copy, Download, Loader2 } from "lucide-react";
import { apiFetch } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { BootstrapResponse } from "@/lib/types";

type Status = "idle" | "loading" | "success" | "error";
type FileKey = "dockerfile" | "docker_compose" | "setup_script";

const FILES: { key: FileKey; label: string; filename: string; mime: string }[] = [
  { key: "dockerfile", label: "Dockerfile", filename: "Dockerfile", mime: "text/plain" },
  { key: "docker_compose", label: "docker-compose.yml", filename: "docker-compose.yml", mime: "text/yaml" },
  { key: "setup_script", label: "setup.sh", filename: "setup.sh", mime: "text/x-sh" },
];

export function BootstrapPanel({ repoId }: { repoId: string }) {
  const [status, setStatus] = useState<Status>("idle");
  const [data, setData] = useState<BootstrapResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<FileKey>("dockerfile");
  const [copied, setCopied] = useState(false);

  // Deterministic (template assembly from already-loaded manifest files, no
  // LLM generation delay) -- fetches automatically on mount, same reasoning
  // as CompliancePanel/RouteExplorerPanel/ModuleMapViewer.
  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    setError(null);

    apiFetch(`/api/repos/${repoId}/bootstrap`, { cache: "no-store" })
      .then(async (res) => {
        if (cancelled) return;
        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: undefined }));
          setError(body.detail ?? "Could not generate setup files.");
          setStatus("error");
          return;
        }
        const json = (await res.json()) as BootstrapResponse;
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

  async function handleCopy(content: string) {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard access denied -- degrades to no visible feedback, same as
      // ReadmeGenerator's identical handler.
    }
  }

  function handleDownload(content: string, filename: string, mime: string) {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  if (status === "idle" || status === "loading") {
    return (
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <motion.span animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: "linear" }}>
          <Loader2 className="h-6 w-6 text-primary" aria-hidden="true" />
        </motion.span>
        <p className="text-sm text-muted-foreground">Reading package manifests...</p>
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

  if (data.stacks_detected.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <p className="text-sm text-muted-foreground">
          No package.json, requirements.txt, or pyproject.toml found -- couldn&apos;t detect a supported stack to
          generate setup files for.
        </p>
      </div>
    );
  }

  const activeFile = FILES.find((f) => f.key === active)!;
  const activeContent = data[active];

  return (
    <div className="flex h-full flex-col gap-2 p-3">
      <p className="text-xs text-muted-foreground">
        Detected: <span className="font-mono text-foreground">{data.stacks_detected.join(", ")}</span>
        {data.services_detected.length > 0 && (
          <>
            {" "}
            + <span className="font-mono text-foreground">{data.services_detected.join(", ")}</span>
          </>
        )}
      </p>

      <div role="tablist" aria-label="Generated setup files" className="flex gap-1">
        {FILES.map((file) => (
          <button
            key={file.key}
            type="button"
            role="tab"
            aria-selected={active === file.key}
            onClick={() => setActive(file.key)}
            className={cn(
              "rounded-full px-3 py-1 text-xs font-medium transition-colors",
              active === file.key ? "bg-primary text-zinc-950" : "text-muted-foreground hover:text-foreground"
            )}
          >
            {file.label}
          </button>
        ))}
      </div>

      <div className="flex items-center justify-end gap-2">
        <Button size="sm" variant="outline" onClick={() => handleCopy(activeContent)}>
          {copied ? <Check className="mr-1 h-3.5 w-3.5" /> : <Copy className="mr-1 h-3.5 w-3.5" />}
          {copied ? "Copied" : "Copy"}
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => handleDownload(activeContent, activeFile.filename, activeFile.mime)}
        >
          <Download className="mr-1 h-3.5 w-3.5" />
          Download
        </Button>
      </div>

      <pre className="glass flex-1 overflow-auto whitespace-pre rounded-md p-3 font-mono text-xs leading-relaxed text-zinc-300">
        {activeContent}
      </pre>
    </div>
  );
}
