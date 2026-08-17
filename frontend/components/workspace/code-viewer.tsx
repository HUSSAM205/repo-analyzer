"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { highlightCode } from "@/lib/highlight";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api-client";
import type { FileContentResponse } from "@/lib/types";

export function CodeViewer({ repoId, path }: { repoId: string; path: string | null }) {
  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!path) {
      setHtml(null);
      setError(null);
      return;
    }

    let cancelled = false;
    setHtml(null);
    setError(null);

    apiFetch(`/api/repos/${repoId}/files/content?path=${encodeURIComponent(path)}`, { cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load file content");
        return res.json() as Promise<FileContentResponse>;
      })
      .then((data) => highlightCode(data.content, path))
      .then((highlighted) => {
        if (!cancelled) setHtml(highlighted);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load this file's content.");
      });

    return () => {
      cancelled = true;
    };
  }, [repoId, path]);

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

  if (html === null) {
    return (
      <div className="space-y-2 p-4">
        {[...Array(12)].map((_, i) => (
          <Skeleton key={i} className="h-4" style={{ width: `${60 + ((i * 13) % 35)}%` }} />
        ))}
      </div>
    );
  }

  return (
    <motion.div
      key={path}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.15 }}
      className="shiki-line-numbers h-full overflow-auto p-4 font-mono text-sm leading-relaxed [&_pre]:!bg-transparent [&_pre]:whitespace-pre"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
