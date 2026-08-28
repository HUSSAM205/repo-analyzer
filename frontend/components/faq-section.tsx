"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";

const FAQ_ITEMS = [
  {
    question: "How does RepoLens AI index large repositories?",
    answer:
      "Analysis runs a zero-token AST tree parse -- files are walked, parsed into an abstract syntax tree, and " +
      "symbols (functions, classes, routes, imports) are extracted directly from that tree. None of this touches " +
      "an LLM, so indexing a large repo costs no tokens and stays fast regardless of how much AI chat you do " +
      "afterward.",
  },
  {
    question: "Is my code secure?",
    answer:
      "Only public GitHub repositories can be analyzed. Processing is ephemeral -- your code is cloned, parsed, " +
      "and held for your session, not used to train any model or retained beyond what's needed to power your " +
      "workspace.",
  },
  {
    question: "Which programming languages and frameworks are supported?",
    answer:
      "AST parsing covers the languages most real-world repos are written in -- JavaScript, TypeScript, Python, " +
      "and more -- across common frameworks on each. Files outside that set still show up in the file browser and " +
      "AI chat, just without deep AST-level structural extraction.",
  },
  {
    question: "Is there a limit on repo size?",
    answer:
      "Yes -- very large repositories are capped to keep analysis fast and reliable for everyone. Most real-world " +
      "projects fall comfortably within the limit; if a repo is rejected for size, trimming unrelated assets or " +
      "vendored dependencies from what gets analyzed usually resolves it.",
  },
];

export function FaqSection() {
  const [openIndexes, setOpenIndexes] = useState<Set<number>>(new Set([0]));

  function toggle(index: number) {
    setOpenIndexes((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  }

  return (
    <section aria-labelledby="faq-heading" className="mb-12">
      <h2 id="faq-heading" className="mb-6 text-xl font-semibold text-foreground">
        Frequently asked questions
      </h2>
      <div className="flex flex-col gap-3">
        {FAQ_ITEMS.map((item, index) => {
          const isOpen = openIndexes.has(index);
          const panelId = `faq-panel-${index}`;
          return (
            <div
              key={item.question}
              className="glass overflow-hidden rounded-xl border border-border/60 bg-white/70 dark:bg-zinc-900/50"
            >
              <button
                type="button"
                onClick={() => toggle(index)}
                aria-expanded={isOpen}
                aria-controls={panelId}
                className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left text-sm font-medium text-foreground transition-colors hover:text-primary"
              >
                {item.question}
                <ChevronDown
                  className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200 ${isOpen ? "rotate-180" : ""}`}
                  aria-hidden="true"
                />
              </button>
              <div
                id={panelId}
                role="region"
                aria-labelledby={panelId}
                className="grid transition-[grid-template-rows] duration-200 ease-out"
                style={{ gridTemplateRows: isOpen ? "1fr" : "0fr" }}
              >
                <div className="overflow-hidden">
                  <p className="px-5 pb-4 text-sm text-muted-foreground">{item.answer}</p>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
