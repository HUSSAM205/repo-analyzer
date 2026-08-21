"use client";

import { useRef, useState } from "react";
import { BarChart3, Bot, Sparkles, Zap } from "lucide-react";
import { HeroCanvas } from "@/components/hero-canvas";
import { SubmitRepoForm, type SubmitRepoFormHandle } from "@/components/submit-repo-form";
import { TiltCard } from "@/components/tilt-card";

const DEMO_REPOS = [
  { label: "facebook/react", url: "https://github.com/facebook/react" },
  { label: "pallets/flask", url: "https://github.com/pallets/flask" },
  { label: "vercel/next.js", url: "https://github.com/vercel/next.js" },
];

const FEATURES = [
  { icon: Zap, label: "Instant AST Parsing" },
  { icon: Bot, label: "AI Codebase Chat" },
  { icon: BarChart3, label: "Architectural Insights" },
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
    <section className="relative isolate mb-12 overflow-hidden rounded-2xl glass px-6 py-16 sm:px-10 sm:py-20">
      <HeroCanvas />
      <div className="relative mx-auto flex max-w-2xl flex-col items-center gap-6 text-center">
        <span className="glow-pill glass inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium text-muted-foreground">
          <Sparkles className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
          AI-powered repository intelligence
        </span>

        <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">
          Understand any codebase <span className="gradient-text">in minutes, not days</span>
        </h1>

        <p className="text-balance max-w-lg text-muted-foreground">
          Paste a GitHub URL and get instant AST-level parsing, an architectural briefing, and an AI chat that
          actually knows your codebase.
        </p>

        <div className="w-full max-w-lg">
          <SubmitRepoForm ref={formRef} />
        </div>

        <div className="flex flex-wrap items-center justify-center gap-2">
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

        <div className="mt-4 grid w-full grid-cols-1 gap-3 sm:grid-cols-3">
          {FEATURES.map((feature) => (
            <TiltCard key={feature.label} className="glass rounded-xl p-4 text-left text-sm">
              <feature.icon className="mb-2 h-5 w-5 text-primary" aria-hidden="true" />
              <p className="font-medium text-foreground">{feature.label}</p>
            </TiltCard>
          ))}
        </div>
      </div>
    </section>
  );
}
