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
      setUrl("");
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
        placeholder="https://github.com/owner/repo"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        aria-label="GitHub repository URL"
        className="focus-visible:elevated-ring"
      />
      <Button type="submit" disabled={submitting}>
        {submitting ? "Submitting..." : "Analyze"}
      </Button>
      {error && <p className="text-sm text-destructive">{error}</p>}
    </motion.form>
  );
}
