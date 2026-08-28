"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Check, Copy, Download, FileText, Loader2 } from "lucide-react";
import { apiFetch } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import type { ReadmeResponse } from "@/lib/types";

type Status = "idle" | "loading" | "success" | "error";

export function ReadmeGenerator({ repoId }: { repoId: string }) {
  const [status, setStatus] = useState<Status>("idle");
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function generate() {
    setStatus("loading");
    setError(null);
    try {
      const res = await apiFetch(`/api/repos/${repoId}/readme`, { cache: "no-store" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: undefined }));
        setError(body.detail ?? "Could not generate documentation.");
        setStatus("error");
        return;
      }
      const data = (await res.json()) as ReadmeResponse;
      setContent(data.content);
      setStatus("success");
    } catch {
      setError("Could not reach the server.");
      setStatus("error");
    }
  }

  async function handleCopy() {
    if (!content) return;
    // navigator.clipboard.writeText rejects (NotAllowedError) when clipboard
    // permission is denied by the browser/embedding context -- caught here
    // so that denial degrades to a no-op instead of an unhandled promise
    // rejection with no user-visible feedback.
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard access denied -- nothing to recover into; the button
      // simply doesn't show the "copied" checkmark.
    }
  }

  function handleDownload() {
    if (!content) return;
    const blob = new Blob([content], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "README.md";
    a.click();
    URL.revokeObjectURL(url);
  }

  if (status === "idle") {
    return (
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <FileText className="h-8 w-8 text-primary" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">
          Generate a README.md draft from this repo&apos;s actual code and structure -- one click.
        </p>
        <Button onClick={generate}>Generate README</Button>
      </div>
    );
  }

  if (status === "loading") {
    return (
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <motion.span animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: "linear" }}>
          <Loader2 className="h-6 w-6 text-primary" aria-hidden="true" />
        </motion.span>
        <p className="text-sm text-muted-foreground">Reading your code and drafting documentation...</p>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <p className="text-sm text-destructive">{error}</p>
        <Button size="sm" variant="outline" onClick={generate}>
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-2 p-3">
      <div className="flex items-center justify-end gap-2">
        <Button size="sm" variant="outline" onClick={handleCopy}>
          {copied ? <Check className="mr-1 h-3.5 w-3.5" /> : <Copy className="mr-1 h-3.5 w-3.5" />}
          {copied ? "Copied" : "Copy"}
        </Button>
        <Button size="sm" variant="outline" onClick={handleDownload}>
          <Download className="mr-1 h-3.5 w-3.5" />
          Download
        </Button>
      </div>
      <pre className="glass flex-1 overflow-auto whitespace-pre-wrap rounded-md p-3 font-mono text-xs leading-relaxed text-zinc-300">
        {content}
      </pre>
    </div>
  );
}
