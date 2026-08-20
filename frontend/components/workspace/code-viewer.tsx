"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Check, Copy } from "lucide-react";
import { exceedsHighlightLimit, highlightCode } from "@/lib/highlight";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api-client";
import type { FileContentResponse } from "@/lib/types";

export function CodeViewer({ repoId, path }: { repoId: string; path: string | null }) {
  const [html, setHtml] = useState<string | null>(null);
  const [rawContent, setRawContent] = useState<string>("");
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tooLarge, setTooLarge] = useState(false);

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
    <div className="sticky top-0 z-10 flex items-center justify-between border-b border-zinc-800/60 bg-card/60 px-4 py-2 backdrop-blur-sm">
      <span className="truncate font-mono text-xs text-zinc-400">{path}</span>
      <button
        type="button"
        onClick={handleCopy}
        aria-label={copied ? "Copied" : "Copy file contents"}
        className="rounded-md border border-zinc-800/60 p-1 text-zinc-400 transition-colors hover:text-zinc-100"
      >
        {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
    </div>
  );

  if (tooLarge) {
    return (
      <div className="flex h-full flex-col">
        {fileHeader}
        <div className="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center">
          <p className="text-sm text-muted-foreground">
            File too large to preview with syntax highlighting ({Math.round(rawContent.length / 1024)} KB).
          </p>
          <p className="text-xs text-muted-foreground">
            You can still copy its contents using the button above.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {fileHeader}
      <motion.div
        key={path}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.15 }}
        className="shiki-line-numbers flex-1 overflow-auto p-4 font-mono text-sm leading-relaxed [&_pre]:!bg-transparent [&_pre]:whitespace-pre"
        dangerouslySetInnerHTML={{ __html: html as string }}
      />
    </div>
  );
}
