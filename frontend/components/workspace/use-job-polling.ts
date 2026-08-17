"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api-client";
import type { Job } from "@/lib/types";

const POLL_INTERVAL_MS = 2000;
const TERMINAL_STATUSES = new Set(["completed", "failed"]);

export function useJobPolling(jobId: string | undefined): { job: Job | null; polling: boolean } {
  const [job, setJob] = useState<Job | null>(null);
  const [polling, setPolling] = useState(Boolean(jobId));

  useEffect(() => {
    if (!jobId) {
      setPolling(false);
      return;
    }

    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout>;

    async function poll() {
      try {
        const res = await apiFetch(`/api/jobs/${jobId}`, { cache: "no-store" });
        if (!res.ok) {
          if (!cancelled) setPolling(false);
          return;
        }
        const data = (await res.json()) as Job;
        if (cancelled) return;
        setJob(data);
        if (TERMINAL_STATUSES.has(data.status)) {
          setPolling(false);
          return;
        }
        timeoutId = setTimeout(poll, POLL_INTERVAL_MS);
      } catch {
        if (!cancelled) setPolling(false);
      }
    }

    setPolling(true);
    poll();

    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
    };
  }, [jobId]);

  return { job, polling };
}
