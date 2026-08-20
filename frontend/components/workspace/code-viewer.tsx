"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Check, Copy, Sparkles } from "lucide-react";
import { exceedsHighlightLimit, highlightCode } from "@/lib/highlight";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type { CodeBlockAnnotation, FileAnnotationsResponse, FileContentResponse } from "@/lib/types";

type ViewMode = "raw" | "annotated";
type AnnotationsStatus = "idle" | "loading" | "success" | "error";
type AnnotationsErrorKind = "too_large" | "unavailable" | "generic" | null;

// Distinct accent color per category, matching the backend contract's
// closed set exactly -- a mismatch here would break rendering on real data.
const CATEGORY_CONFIG: Record<CodeBlockAnnotation["category"], { label: string; badgeClass: string }> = {
  imports: {
    label: "Imports",
    badgeClass: "border-sky-500/40 bg-sky-500/10 text-sky-300 ring-sky-500/30 shadow-[0_0_10px_-2px_rgba(56,189,248,0.5)]",
  },
  config_state: {
    label: "Config & State",
    badgeClass: "border-amber-500/40 bg-amber-500/10 text-amber-300 ring-amber-500/30 shadow-[0_0_10px_-2px_rgba(245,158,11,0.5)]",
  },
  business_logic: {
    label: "Business Logic",
    badgeClass: "border-violet-500/40 bg-violet-500/10 text-violet-300 ring-violet-500/30 shadow-[0_0_10px_-2px_rgba(139,92,246,0.5)]",
  },
  handlers_endpoints: {
    label: "Handlers & Endpoints",
    badgeClass: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300 ring-emerald-500/30 shadow-[0_0_10px_-2px_rgba(52,211,153,0.5)]",
  },
};

export function CodeViewer({ repoId, path }: { repoId: string; path: string | null }) {
  const [html, setHtml] = useState<string | null>(null);
  const [rawContent, setRawContent] = useState<string>("");
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tooLarge, setTooLarge] = useState(false);

  const [mode, setMode] = useState<ViewMode>("raw");
  const [annotationsStatus, setAnnotationsStatus] = useState<AnnotationsStatus>("idle");
  const [annotationsErrorKind, setAnnotationsErrorKind] = useState<AnnotationsErrorKind>(null);
  const [annotationsErrorDetail, setAnnotationsErrorDetail] = useState<string | null>(null);
  const [annotations, setAnnotations] = useState<FileAnnotationsResponse | null>(null);
  const [blockHtml, setBlockHtml] = useState<string[]>([]);

  useEffect(() => {
    if (!path) {
      setHtml(null);
      setError(null);
      setTooLarge(false);
      return;
    }

    let cancelled = false;
    setHtml(null);
    setError(null);
    setTooLarge(false);
    setCopied(false);
    // A new file selection starts fresh in Raw Code (today's default
    // behavior) with any previous file's annotations discarded -- an
    // Annotated View fetch is per-path and stale results from the last
    // file must never bleed into the newly selected one.
    setMode("raw");
    setAnnotationsStatus("idle");
    setAnnotationsErrorKind(null);
    setAnnotationsErrorDetail(null);
    setAnnotations(null);
    setBlockHtml([]);

    apiFetch(`/api/repos/${repoId}/files/content?path=${encodeURIComponent(path)}`, { cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load file content");
        return res.json() as Promise<FileContentResponse>;
      })
      .then((data) => {
        if (cancelled) return undefined;
        setRawContent(data.content);
        // Skip the synchronous Shiki tokenize-and-render pass entirely for
        // very large files -- it can noticeably freeze the tab -- and show
        // a fallback state instead of highlighted HTML.
        if (exceedsHighlightLimit(data.content)) {
          setTooLarge(true);
          return undefined;
        }
        return highlightCode(data.content, path);
      })
      .then((highlighted) => {
        if (!cancelled && highlighted) setHtml(highlighted);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load this file's content.");
      });

    return () => {
      cancelled = true;
    };
  }, [repoId, path]);

  async function fetchAnnotations(currentPath: string) {
    setAnnotationsStatus("loading");
    setAnnotationsErrorKind(null);
    setAnnotationsErrorDetail(null);

    try {
      const res = await apiFetch(
        `/api/repos/${repoId}/files/annotations?path=${encodeURIComponent(currentPath)}`,
        { cache: "no-store" }
      );

      if (res.status === 413) {
        const body = await res.json().catch(() => ({ detail: undefined }));
        setAnnotationsErrorKind("too_large");
        setAnnotationsErrorDetail(body.detail ?? "This file is too large to annotate.");
        setAnnotationsStatus("error");
        return;
      }

      if (res.status === 503) {
        const body = await res.json().catch(() => ({ detail: undefined }));
        setAnnotationsErrorKind("unavailable");
        setAnnotationsErrorDetail(body.detail ?? "AI annotation is temporarily unavailable.");
        setAnnotationsStatus("error");
        return;
      }

      if (!res.ok) {
        setAnnotationsErrorKind("generic");
        setAnnotationsErrorDetail(null);
        setAnnotationsStatus("error");
        return;
      }

      const data = (await res.json()) as FileAnnotationsResponse;
      setAnnotations(data);
      setAnnotationsStatus("success");
    } catch {
      setAnnotationsErrorKind("generic");
      setAnnotationsErrorDetail(null);
      setAnnotationsStatus("error");
    }
  }

  // Once annotations arrive, highlight each block's raw code slice
  // separately (reusing the content already fetched for Raw Code -- no
  // re-fetch of file content) rather than the whole-file `html` above,
  // since blocks are rendered independently with their own AI card.
  useEffect(() => {
    if (!annotations || !path) {
      setBlockHtml([]);
      return;
    }
    let cancelled = false;
    const lines = rawContent.split("\n");
    Promise.all(
      annotations.blocks.map((block) => {
        const slice = lines.slice(Math.max(0, block.start_line - 1), block.end_line).join("\n");
        return highlightCode(slice, path).catch(() => `<pre><code>${slice}</code></pre>`);
      })
    ).then((htmls) => {
      if (!cancelled) setBlockHtml(htmls);
    });
    return () => {
      cancelled = true;
    };
  }, [annotations, rawContent, path]);

  function handleModeChange(next: ViewMode) {
    setMode(next);
    if (next === "annotated" && path && annotationsStatus === "idle") {
      fetchAnnotations(path);
    }
  }

  function handleRetryAnnotations() {
    if (path) fetchAnnotations(path);
  }

  async function handleCopy() {
    await navigator.clipboard.writeText(rawContent);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  if (!path) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Select a file to view its contents
      </div>
    );
  }

  if (error) {
    return <p className="p-4 text-sm text-destructive">{error}</p>;
  }

  if (!tooLarge && html === null) {
    return (
      <div className="space-y-2 p-4">
        {[...Array(12)].map((_, i) => (
          <Skeleton key={i} className="h-4" style={{ width: `${60 + ((i * 13) % 35)}%` }} />
        ))}
      </div>
    );
  }

  const fileHeader = (
    <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-zinc-800/60 bg-card/60 px-4 py-2 backdrop-blur-sm">
      <span className="truncate font-mono text-xs text-zinc-400">{path}</span>
      <div className="flex shrink-0 items-center gap-2">
        <ViewModeToggle mode={mode} onChange={handleModeChange} />
        <button
          type="button"
          onClick={handleCopy}
          aria-label={copied ? "Copied" : "Copy file contents"}
          className="rounded-md border border-zinc-800/60 p-1 text-zinc-400 transition-colors hover:text-zinc-100"
        >
          {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
      </div>
    </div>
  );

  if (tooLarge) {
    return (
      <div className="flex h-full flex-col">
        {fileHeader}
        {mode === "raw" ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center">
            <p className="text-sm text-muted-foreground">
              File too large to preview with syntax highlighting ({Math.round(rawContent.length / 1024)} KB).
            </p>
            <p className="text-xs text-muted-foreground">
              You can still copy its contents using the button above.
            </p>
          </div>
        ) : (
          <AnnotatedViewBody
            status={annotationsStatus}
            errorKind={annotationsErrorKind}
            errorDetail={annotationsErrorDetail}
            annotations={annotations}
            blockHtml={blockHtml}
            onRetry={handleRetryAnnotations}
          />
        )}
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {fileHeader}
      {mode === "raw" ? (
        <motion.div
          key={path}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.15 }}
          className="shiki-line-numbers flex-1 overflow-auto p-4 font-mono text-sm leading-relaxed [&_pre]:!bg-transparent [&_pre]:whitespace-pre"
          dangerouslySetInnerHTML={{ __html: html as string }}
        />
      ) : (
        <AnnotatedViewBody
          status={annotationsStatus}
          errorKind={annotationsErrorKind}
          errorDetail={annotationsErrorDetail}
          annotations={annotations}
          blockHtml={blockHtml}
          onRetry={handleRetryAnnotations}
        />
      )}
    </div>
  );
}

function ViewModeToggle({ mode, onChange }: { mode: ViewMode; onChange: (mode: ViewMode) => void }) {
  const options: { key: ViewMode; label: string }[] = [
    { key: "raw", label: "Raw Code" },
    { key: "annotated", label: "Annotated View" },
  ];

  return (
    <div
      role="tablist"
      aria-label="Code view mode"
      className="glass relative flex items-center gap-0.5 rounded-full p-0.5"
    >
      {options.map((opt) => (
        <button
          key={opt.key}
          type="button"
          role="tab"
          aria-selected={mode === opt.key}
          onClick={() => onChange(opt.key)}
          className={cn(
            "relative rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors",
            mode === opt.key ? "text-zinc-950" : "text-zinc-400 hover:text-zinc-200"
          )}
        >
          {mode === opt.key && (
            <motion.span
              layoutId="code-view-mode-pill"
              className="absolute inset-0 -z-10 rounded-full bg-primary shadow-[0_0_10px_-1px_hsl(var(--primary)/0.55)]"
              transition={{ duration: 0.2, ease: "easeInOut" }}
            />
          )}
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function AnnotatedViewBody({
  status,
  errorKind,
  errorDetail,
  annotations,
  blockHtml,
  onRetry,
}: {
  status: AnnotationsStatus;
  errorKind: AnnotationsErrorKind;
  errorDetail: string | null;
  annotations: FileAnnotationsResponse | null;
  blockHtml: string[];
  onRetry: () => void;
}) {
  if (status === "idle" || status === "loading") {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
        <motion.span
          className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/10 text-primary ring-1 ring-primary/30"
          animate={{ opacity: [1, 0.4, 1] }}
          transition={{ duration: 1.2, repeat: Infinity, ease: "easeInOut" }}
        >
          <Sparkles className="h-4 w-4" />
        </motion.span>
        <p className="text-sm text-zinc-300">AI is analyzing this file...</p>
        <p className="text-xs text-muted-foreground">
          First look can take a few seconds -- later visits load instantly from cache.
        </p>
      </div>
    );
  }

  if (status === "error") {
    if (errorKind === "too_large") {
      return (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center">
          <p className="text-sm text-muted-foreground">
            {errorDetail ?? "This file is too large to annotate."}
          </p>
        </div>
      );
    }

    if (errorKind === "unavailable") {
      return (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
          <p className="text-sm text-destructive">
            {errorDetail ?? "AI annotation is temporarily unavailable."}
          </p>
          <Button size="sm" variant="outline" onClick={onRetry}>
            Retry
          </Button>
        </div>
      );
    }

    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center">
        <p className="text-sm text-destructive">Could not load annotations for this file.</p>
      </div>
    );
  }

  if (!annotations || annotations.blocks.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-6 text-center text-sm text-muted-foreground">
        No annotated blocks were found for this file.
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-auto p-4">
      {annotations.blocks.map((block, i) => {
        const config = CATEGORY_CONFIG[block.category];
        return (
          <motion.div
            key={`${block.category}-${block.start_line}-${block.end_line}`}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2, ease: "easeInOut", delay: Math.min(i * 0.03, 0.3) }}
            className={cn(i > 0 && "mt-4 border-t border-zinc-800/60 pt-4")}
          >
            <div className="mb-2 flex items-center justify-between gap-2">
              <span
                className={cn(
                  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-semibold tracking-wide ring-1 ring-inset",
                  config.badgeClass
                )}
              >
                {config.label}
              </span>
              <span className="font-mono text-[11px] text-zinc-500">
                L{block.start_line}-{block.end_line}
              </span>
            </div>
            <div
              className="overflow-auto rounded-md border border-zinc-800/60 bg-card/40 p-3 font-mono text-sm leading-relaxed [&_pre]:!bg-transparent [&_pre]:whitespace-pre"
              dangerouslySetInnerHTML={{ __html: blockHtml[i] ?? "<pre><code></code></pre>" }}
            />
            <div className="glass mt-2 space-y-2 rounded-md p-3">
              <AnnotationField label="Logic Summary" value={block.logic_summary} />
              <AnnotationField label="Flow" value={block.flow} />
              <AnnotationField label="Tips" value={block.tips} />
            </div>
          </motion.div>
        );
      })}
    </div>
  );
}

function AnnotationField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-primary/80">{label}</p>
      <p className="text-xs leading-relaxed text-zinc-300">{value}</p>
    </div>
  );
}
