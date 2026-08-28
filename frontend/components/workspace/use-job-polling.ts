"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api-client";
import type { Job } from "@/lib/types";

const POLL_INTERVAL_MS = 2000;
const TERMINAL_STATUSES = new Set(["completed", "failed"]);

// A single dropped request (brief backend blip, proxy hiccup) shouldn't be
// treated the same as the job actually being unreachable -- retry a few
// times with increasing backoff before giving up.
const MAX_RETRIES = 4;
const RETRY_BASE_DELAY_MS = 1000;

export function useJobPolling(jobId: string | undefined): {
  job: Job | null;
  polling: boolean;
  // True once retries are exhausted after a run of consecutive poll
  // failures. Distinct from `polling` -- `job` is left untouched (it keeps
  // whatever it last successfully fetched), so callers need this separate
  // signal to tell "still analyzing" apart from "we lost track of it".
  pollingFailed: boolean;
} {
  const [job, setJob] = useState<Job | null>(null);
  const [polling, setPolling] = useState(Boolean(jobId));
  const [pollingFailed, setPollingFailed] = useState(false);

  useEffect(() => {
    if (!jobId) {
      setPolling(false);
      setPollingFailed(false);
      return;
    }

    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout>;
    let retryCount = 0;

    async function poll() {
      try {
        const res = await apiFetch(`/api/jobs/${jobId}`, { cache: "no-store" });
        if (!res.ok) {
          throw new Error(`Job poll failed with status ${res.status}`);
        }
        const data = (await res.json()) as Job;
        if (cancelled) return;

        retryCount = 0;
        setPollingFailed(false);
        setJob(data);

        if (TERMINAL_STATUSES.has(data.status)) {
          setPolling(false);
          return;
        }
        timeoutId = setTimeout(poll, POLL_INTERVAL_MS);
      } catch {
        if (cancelled) return;

        if (retryCount < MAX_RETRIES) {
          retryCount += 1;
          const delay = RETRY_BASE_DELAY_MS * 2 ** (retryCount - 1);
          timeoutId = setTimeout(poll, delay);
          return;
        }

        // Retries exhausted -- surface a distinct "lost connection" signal
        // rather than silently keeping stale `job` data with no indication
        // anything is wrong.
        setPolling(false);
        setPollingFailed(true);
      }
    }

    setPolling(true);
    setPollingFailed(false);
    poll();

    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
    };
  }, [jobId]);

  return { job, polling, pollingFailed };
}
