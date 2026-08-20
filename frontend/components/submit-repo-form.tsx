"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type { AnalyzeRepoResponse } from "@/lib/types";

export function SubmitRepoForm({ compact = false }: { compact?: boolean } = {}) {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
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
        body: JSON.stringify({ repo_url: url }),
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

  return (
    <motion.form
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2 }}
      onSubmit={handleSubmit}
      className={cn("glass flex items-center gap-2 rounded-lg", compact ? "p-1.5" : "p-3")}
    >
      <Input
        type="url"
        required
        disabled={submitting}
        placeholder="https://github.com/owner/repo"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        aria-label="GitHub repository URL"
      />
      <Button type="submit" disabled={submitting}>
        {submitting ? "Submitting..." : "Analyze"}
      </Button>
      {error && <p className="text-sm text-destructive">{error}</p>}
    </motion.form>
  );
}
