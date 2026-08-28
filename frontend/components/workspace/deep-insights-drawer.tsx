"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown } from "lucide-react";
import type { DomainBriefing } from "@/lib/types";

// The beginner-facing "onboarding guide" fields of a repo's briefing (see
// app.core.domain_briefing.generate_domain_briefing), relocated here out of
// RepoBriefing's always-visible card into an on-demand dropdown triggered
// from RepoHeader -- keeps the workspace header minimal by default while
// still putting the analogy/tech-stack/reading-path content one click away.
export function DeepInsightsDrawer({ briefing }: { briefing: DomainBriefing | null | undefined }) {
  const [open, setOpen] = useState(false);

  const techExplained = briefing?.tech_stack_explained ?? [];
  const learningPath = briefing?.learning_path ?? [];
  const takeaways = briefing?.key_takeaways ?? [];
  const hasContent = !!briefing?.beginner_summary || techExplained.length > 0 || learningPath.length > 0 || takeaways.length > 0;

  if (!hasContent) return null;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center gap-1 rounded-md px-2 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        Deep Insights
        <motion.span animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.15, ease: "easeInOut" }}>
          <ChevronDown className="h-3.5 w-3.5" />
        </motion.span>
      </button>

      <AnimatePresence>
        {open && (
          <>
            {/* Click-outside-to-close backdrop -- invisible, just catches the click. */}
            <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} aria-hidden="true" />
            <motion.div
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.18, ease: "easeInOut" }}
              className="glass absolute right-0 top-full z-30 mt-2 max-h-[70vh] w-[min(90vw,420px)] overflow-y-auto rounded-xl border border-border p-4 shadow-xl"
            >
              <div className="space-y-3">
                {briefing?.beginner_summary && (
                  <InsightSection emoji="🎯" title="What is this project?">
                    <p className="text-sm leading-relaxed text-zinc-300">{briefing.beginner_summary}</p>
                  </InsightSection>
                )}

                {techExplained.length > 0 && (
                  <InsightSection emoji="🛠️" title="Tech stack explained">
                    <ul className="space-y-1.5">
                      {techExplained.map((entry) => (
                        <li key={entry.name} className="text-sm leading-relaxed text-zinc-300">
                          <span className="font-mono font-semibold text-zinc-100">{entry.name}</span>
                          {" = "}
                          {entry.role}
                        </li>
                      ))}
                    </ul>
                  </InsightSection>
                )}

                {learningPath.length > 0 && (
                  <InsightSection emoji="🚦" title="Where should I start?">
                    <ol className="space-y-1.5">
                      {learningPath.map((step, i) => (
                        <li key={`${step.file_or_topic}-${i}`} className="flex gap-2 text-sm leading-relaxed text-zinc-300">
                          <span className="shrink-0 font-mono text-xs text-primary">{i + 1}.</span>
                          <span>
                            <span className="font-mono font-semibold text-zinc-100">{step.file_or_topic}</span>
                            {" -- "}
                            {step.why}
                          </span>
                        </li>
                      ))}
                    </ol>
                  </InsightSection>
                )}

                {takeaways.length > 0 && (
                  <InsightSection emoji="💡" title="Key takeaways & best practices">
                    <ul className="list-disc space-y-1 pl-4">
                      {takeaways.map((point, i) => (
                        <li key={i} className="text-sm leading-relaxed text-zinc-300">
                          {point}
                        </li>
                      ))}
                    </ul>
                  </InsightSection>
                )}
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  );
}

function InsightSection({ emoji, title, children }: { emoji: string; title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-primary/80">
        <span aria-hidden="true">{emoji}</span>
        {title}
      </p>
      {children}
    </div>
  );
}
