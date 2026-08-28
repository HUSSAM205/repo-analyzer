"use client";

import { useRef, useState } from "react";
import { motion } from "framer-motion";
import { MockTerminal } from "@/components/mock-terminal";
import { SubmitRepoForm, type SubmitRepoFormHandle } from "@/components/submit-repo-form";
import { HeroGlowBackground } from "@/components/hero-glow-background";
import { HeroFeatureTiles } from "@/components/hero-feature-tiles";
import { BrandNode } from "@/components/brand-node";

// Popular, well-known repos across different ecosystems (Node backend,
// Python backend, JS frontend state) -- deliberately pre-analyzed once
// (see the deploy notes for this change) so these specific three are
// already cached and clicking one is instant for a real visitor, not a
// multi-second clone-and-parse wait.
const DEMO_REPOS = [
  { label: "expressjs/express", url: "https://github.com/expressjs/express" },
  { label: "tiangolo/fastapi", url: "https://github.com/tiangolo/fastapi" },
  { label: "reduxjs/redux", url: "https://github.com/reduxjs/redux" },
];

export function Hero() {
  const formRef = useRef<SubmitRepoFormHandle>(null);
  const [pendingDemo, setPendingDemo] = useState<string | null>(null);

  async function handleDemoClick(url: string) {
    if (pendingDemo) return;
    setPendingDemo(url);
    try {
      await formRef.current?.submitUrl(url);
    } finally {
      setPendingDemo(null);
    }
  }

  return (
    <section
      className="relative isolate mb-12 overflow-hidden rounded-2xl border shadow-xl backdrop-blur-xl
        border-zinc-200/90 bg-white/70 shadow-zinc-300/30
        dark:border-zinc-800/80 dark:bg-zinc-900/60 dark:shadow-2xl dark:shadow-indigo-500/10"
    >
      <HeroGlowBackground />
      <div className="relative mx-auto flex max-w-5xl flex-col items-center gap-8 px-6 py-16 text-center sm:px-10 sm:py-20">
        <span className="glow-pill glass inline-flex items-center gap-2 rounded-full px-3 py-1 font-mono text-[11px] uppercase tracking-wide text-muted-foreground">
          <span className="relative flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-primary" />
          </span>
          RepoLens AI &bull; Next-Gen Repo Intelligence
        </span>

        <h1 className="max-w-2xl text-4xl font-bold tracking-tight sm:text-5xl">
          <span className="bg-gradient-to-r from-zinc-950 to-zinc-600 bg-clip-text text-transparent dark:from-white dark:to-zinc-400">
            Paste a repo.
          </span>{" "}
          <span className="gradient-text">Get a workbench.</span>
        </h1>

        <p className="text-balance max-w-lg text-muted-foreground">
          AST-level parsing, route extraction, and complexity analysis run instantly with zero LLM tokens -- the AI
          chat is there when you need it to reason about the rest.
        </p>

        <div className="grid w-full max-w-4xl grid-cols-1 items-center gap-6 text-left lg:grid-cols-2">
          <div className="flex flex-col gap-3">
            <SubmitRepoForm ref={formRef} />
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-muted-foreground">Try it instantly:</span>
              {DEMO_REPOS.map((demo) => (
                <button
                  key={demo.url}
                  type="button"
                  onClick={() => handleDemoClick(demo.url)}
                  disabled={pendingDemo !== null}
                  className="glow-pill glass rounded-full px-3 py-1 font-mono text-xs text-foreground transition-colors hover:border-primary/50 disabled:opacity-50"
                >
                  {pendingDemo === demo.url ? "Analyzing..." : demo.label}
                </button>
              ))}
            </div>
          </div>
          <div className="flex flex-col items-center gap-6 lg:items-end">
            <MockTerminal />
            <BrandNode />
          </div>
        </div>

        <div className="mt-4 w-full">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            See it in action
          </p>
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, ease: "easeOut" }}
          >
            <HeroFeatureTiles />
          </motion.div>
        </div>
      </div>
    </section>
  );
}
