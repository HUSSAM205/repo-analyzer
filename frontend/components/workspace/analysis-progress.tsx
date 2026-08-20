"use client";

import { motion } from "framer-motion";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Job } from "@/lib/types";

type Stage = NonNullable<Job["stage"]>;

const STAGES: { key: Stage; label: string }[] = [
  { key: "cloning", label: "Cloning repository..." },
  { key: "parsing", label: "Detecting domain & parsing AST..." },
  { key: "embedding", label: "Generating CodeBERT embeddings..." },
  { key: "completed", label: "Ready!" },
];

// Multi-stage animated progress indicator shown in place of `RepoBriefing`
// while a job is in a non-terminal status (`pending`/`running`) -- see
// app/repos/[repoId]/page.tsx. `stage` is optional/nullable (a
// not-yet-updated backend deploy may not send it at all): default to the
// first stage in that case rather than rendering nothing, since the job is
// still known to be in progress.
export function AnalysisProgress({ stage }: { stage: Job["stage"] | null | undefined }) {
  const idx = stage ? STAGES.findIndex((s) => s.key === stage) : -1;
  const currentIndex = idx === -1 ? 0 : idx;

  return (
    <section className="border-b border-zinc-800/60 px-4 py-5" data-testid="analysis-progress">
      <ol className="flex items-start justify-between gap-1 sm:gap-3">
        {STAGES.map((s, i) => {
          const isDone = i < currentIndex;
          const isCurrent = i === currentIndex;
          const isUpcoming = !isDone && !isCurrent;

          return (
            <li key={s.key} className="flex flex-1 flex-col items-center gap-2">
              <div className="flex w-full items-center">
                <div
                  className={cn(
                    "h-px flex-1 transition-colors duration-200",
                    i === 0 ? "opacity-0" : isDone || isCurrent ? "bg-primary/60" : "bg-zinc-800/60"
                  )}
                />
                <motion.div
                  aria-label={
                    isDone ? `${s.label} (done)` : isCurrent ? `${s.label} (in progress)` : `${s.label} (upcoming)`
                  }
                  className={cn(
                    "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-xs font-medium transition-colors duration-200",
                    isDone && "border-emerald-400/70 bg-emerald-400/10 text-emerald-400",
                    isCurrent && "border-primary bg-primary/10 text-primary",
                    isUpcoming && "border-zinc-800/60 text-zinc-600"
                  )}
                  animate={isCurrent ? { opacity: [1, 0.5, 1] } : { opacity: 1 }}
                  transition={{ duration: 1.4, repeat: isCurrent ? Infinity : 0, ease: "easeInOut" }}
                >
                  {isDone ? <Check className="h-3.5 w-3.5" /> : i + 1}
                </motion.div>
                <div
                  className={cn(
                    "h-px flex-1 transition-colors duration-200",
                    i === STAGES.length - 1 ? "opacity-0" : isDone ? "bg-primary/60" : "bg-zinc-800/60"
                  )}
                />
              </div>
              <span
                className={cn(
                  "text-center text-[11px] leading-tight transition-colors duration-200 sm:text-xs",
                  isCurrent && "font-medium text-zinc-100",
                  isDone && "text-zinc-300",
                  isUpcoming && "text-zinc-600"
                )}
              >
                {s.label}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
