"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, ChevronUp, Globe2 } from "lucide-react";
import type { DomainBriefing } from "@/lib/types";

// A dedicated, always-visible-but-collapsed entry point for
// `briefing.beginner_summary` (an LLM-written everyday-life analogy for
// what the repo does -- see app.core.domain_briefing._SYSTEM_PROMPT) at the
// very top of the workspace, above RepoBriefing. That same text was already
// reachable via DeepInsightsDrawer's "Deep Insights" dropdown, but tucked
// behind an extra click and mixed in with denser reference material
// (tech-stack table, reading order, takeaways) -- this surfaces just the
// analogy on its own, as the very first thing a total beginner sees.
export function Eli10Card({ briefing }: { briefing: DomainBriefing | null | undefined }) {
  const [expanded, setExpanded] = useState(false);

  if (!briefing?.beginner_summary) return null;

  return (
    <section className="glass border-b border-border/60 px-4 py-2.5">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="flex w-full items-center justify-between gap-3 text-left"
      >
        <span className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-primary/80">
          <Globe2 className="h-3.5 w-3.5" aria-hidden="true" />
          ELI10 -- Explain like I&apos;m 10
        </span>
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
            <p className="pt-2 text-sm leading-relaxed text-foreground/90">{briefing.beginner_summary}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}
