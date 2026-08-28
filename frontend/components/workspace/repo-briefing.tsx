"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, ChevronUp } from "lucide-react";
import type { DomainBriefing } from "@/lib/types";

// Executive "briefing" card summarizing what a repo is and who it's for --
// the first thing a visitor reads, above the file tree/code viewer/chat
// workspace (see app/repos/[repoId]/page.tsx). `briefing` is optional/
// nullable: it's absent while a job is still analyzing (that state is
// covered by `AnalysisProgress` instead, rendered in the same page slot)
// and may also be null on a repo analyzed before this feature existed --
// in that case, show a subtle placeholder rather than an empty card.
export function RepoBriefing({ briefing }: { briefing: DomainBriefing | null | undefined }) {
  const [expanded, setExpanded] = useState(true);

  if (!briefing) {
    return (
      <div className="border-b border-border/60 px-4 py-3 text-xs text-muted-foreground">
        Briefing not available yet.
      </div>
    );
  }

  const distribution = briefing.file_type_distribution ?? [];
  const badges = briefing.tech_stack_badges ?? [];

  return (
    <section className="glass border-b border-border/60 px-4 py-3">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        aria-label="Toggle repo briefing"
        className="flex w-full items-center justify-between gap-3 text-left"
      >
        <div className="flex min-w-0 items-center gap-2">
          <span className="glow-pill shrink-0 rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold tracking-wide text-primary">
            {briefing.primary_field}
          </span>
          {!expanded && (
            <span className="truncate text-xs text-muted-foreground">{briefing.target_audience}</span>
          )}
        </div>
        {expanded ? (
          <ChevronUp className="h-4 w-4 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
        )}
      </button>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            <div className="space-y-3 pt-3">
              <p className="text-xs text-muted-foreground">{briefing.target_audience}</p>

              {badges.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {badges.map((badge) => (
                    <span
                      key={badge}
                      className="glow-pill rounded-full border border-border/60 px-3 py-1.5 text-xs text-foreground/80"
                    >
                      {badge}
                    </span>
                  ))}
                </div>
              )}

              {distribution.length > 0 && (
                <p className="text-xs text-muted-foreground">
                  {distribution.map((f) => `${f.count} ${f.label}`).join(" · ")}
                </p>
              )}

              <p className="text-sm leading-relaxed text-foreground/90">{briefing.architecture_overview}</p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}
