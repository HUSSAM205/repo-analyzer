"use client";

import { forwardRef, useImperativeHandle, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type { AnalyzeRepoResponse } from "@/lib/types";

// Deliberately loose (owner/repo, optionally trailing slash or .git) --
// this only drives a live visual hint, never blocks submission, so a false
// negative on some valid-but-unusual GitHub URL shape costs nothing.
const GITHUB_REPO_URL_RE = /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/?(?:\.git)?$/;

export interface SubmitRepoFormHandle {
  /** Fills the field with `url` and submits it, as if the user had typed and clicked Analyze. */
  submitUrl: (url: string) => Promise<void>;
}

export const SubmitRepoForm = forwardRef<SubmitRepoFormHandle, { compact?: boolean }>(function SubmitRepoForm(
  { compact = false },
  ref
) {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(targetUrl: string) {
    // Defense in depth alongside the Button's `disabled` attribute (and now
    // the Input's) -- neither is a hard guarantee against a re-entrant
    // submit (e.g. a fast double Enter-key press before React re-renders
    // the disabled state), so bail out explicitly too.
    if (submitting) return;
    setError(null);
    setSubmitting(true);
    try {
      const res = await apiFetch("/api/repos", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_url: targetUrl }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: "Could not submit repo" }));
        setError(body.detail ?? "Could not submit repo");
        setSubmitting(false);
        return;
      }
      const data = (await res.json()) as AnalyzeRepoResponse;
      // Deliberately not clearing `url` here: SubmitRepoForm lives in
      // AppHeader, a layout-level component that persists across the
      // client-side navigation below, so clearing it would flash the input
      // empty before the new page even renders. Leaving it populated means
      // the URL just stays visible -- the user can still clear it manually.
      setSubmitting(false);
      router.refresh();
      router.push(`/repos/${data.repo_id}?job=${data.job_id}`);
    } catch {
      setError("Could not reach the server. Please try again.");
      setSubmitting(false);
    }
  }

  useImperativeHandle(ref, () => ({
    submitUrl: async (targetUrl: string) => {
      setUrl(targetUrl);
      await submit(targetUrl);
    },
  }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    await submit(url);
  }

  const isValidGithubUrl = GITHUB_REPO_URL_RE.test(url.trim());

  return (
    <motion.form
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2 }}
      onSubmit={handleSubmit}
      className={cn(
        "glass flex items-center gap-2 rounded-lg transition-shadow",
        compact ? "p-1.5" : "rounded-2xl p-2.5 pl-4 shadow-sm transition-all focus-within:shadow-[0_0_0_1px_hsl(var(--primary)/0.5),0_0_24px_-4px_hsl(var(--primary)/0.35)] dark:shadow-none",
        !compact && url.length > 0 && (isValidGithubUrl ? "ring-1 ring-emerald-500/40" : "ring-1 ring-border")
      )}
    >
      {!compact && <span className="pl-1 font-mono text-sm text-muted-foreground">$</span>}
      <Input
        type="url"
        required
        disabled={submitting}
        placeholder="https://github.com/owner/repo"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        aria-label="GitHub repository URL"
        className={cn(!compact && "border-none bg-transparent font-mono shadow-none focus-visible:ring-0")}
      />
      {!compact && url.length === 0 && (
        <kbd
          aria-hidden="true"
          className="hidden shrink-0 rounded border border-border bg-accent px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground sm:inline-block"
        >
          ↵ Enter
        </kbd>
      )}
      {!compact && isValidGithubUrl && (
        <Check className="h-4 w-4 shrink-0 text-emerald-400" aria-label="Valid GitHub repository URL" />
      )}
      <Button
        type="submit"
        disabled={submitting}
        className={cn(
          !compact &&
            "shrink-0 rounded-xl bg-gradient-to-r from-primary to-indigo-500 px-5 text-primary-foreground shadow-[0_0_16px_-2px_hsl(var(--primary)/0.5)] hover:from-primary hover:to-indigo-400 hover:shadow-[0_0_20px_-2px_hsl(var(--primary)/0.65)]"
        )}
      >
        {submitting ? "Submitting..." : compact ? "Analyze" : "Analyze Repository →"}
      </Button>
      {error && <p className="text-sm text-destructive">{error}</p>}
    </motion.form>
  );
});
