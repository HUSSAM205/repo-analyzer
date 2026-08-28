"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";

// Purely illustrative -- not a live command, and deliberately not claiming
// to be one (no blinking "connecting..." framing). Every line here mirrors
// a real, deterministic (0-LLM-token) step this app actually performs on
// analysis: AST parsing (ast_parser.py), route extraction
// (route_explorer.py), module structure (module_map.py), and complexity
// scoring (complexity_radar.py) -- not a fabricated demo of a capability
// that doesn't exist.
const LINES: { text: string; delayMs: number; tone?: "muted" | "accent" }[] = [
  { text: "$ repolens analyze ./your-repo", delayMs: 0 },
  { text: "→ parsing AST (tree-sitter: py, js, ts, go, java)", delayMs: 500, tone: "muted" },
  { text: "  ✓ 1,138 files parsed, 4,209 symbols indexed", delayMs: 950, tone: "accent" },
  { text: "→ extracting routes (FastAPI / Express / Next.js)", delayMs: 1500, tone: "muted" },
  { text: "  ✓ 42 endpoints found, 12 unauthenticated", delayMs: 1950, tone: "accent" },
  { text: "→ scanning for secrets & dangerous patterns", delayMs: 2500, tone: "muted" },
  { text: "  ✓ 0 findings -- 0 LLM tokens used", delayMs: 2950, tone: "accent" },
  { text: "→ scoring cyclomatic complexity", delayMs: 3500, tone: "muted" },
  { text: "  ✓ done -- avg 3.2, 5 hotspots flagged", delayMs: 3950, tone: "accent" },
];

const TOTAL_DURATION_MS = LINES[LINES.length - 1].delayMs + 600;

export function MockTerminal() {
  const [visibleCount, setVisibleCount] = useState(LINES.length);

  useEffect(() => {
    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReducedMotion) return; // static, fully-revealed -- no timers

    setVisibleCount(0);
    const timers = LINES.map((line, i) => setTimeout(() => setVisibleCount(i + 1), line.delayMs));
    const loop = setInterval(() => setVisibleCount(0), TOTAL_DURATION_MS + 1200);
    const restart = setTimeout(() => {
      LINES.forEach((line, i) => setTimeout(() => setVisibleCount(i + 1), line.delayMs));
    }, TOTAL_DURATION_MS + 1200);

    return () => {
      timers.forEach(clearTimeout);
      clearInterval(loop);
      clearTimeout(restart);
    };
  }, []);

  return (
    <div className="glass w-full max-w-lg overflow-hidden rounded-xl border border-zinc-800/60 text-left">
      <div className="flex items-center gap-1.5 border-b border-zinc-800/60 bg-zinc-900/60 px-3 py-2">
        <span className="h-2.5 w-2.5 rounded-full bg-zinc-700" />
        <span className="h-2.5 w-2.5 rounded-full bg-zinc-700" />
        <span className="h-2.5 w-2.5 rounded-full bg-zinc-700" />
        <span className="ml-2 font-mono text-[11px] text-muted-foreground">repolens -- analysis</span>
      </div>
      <div className="space-y-1 p-3.5 font-mono text-[12.5px] leading-relaxed">
        {LINES.slice(0, visibleCount).map((line, i) => (
          <motion.p
            key={i}
            initial={{ opacity: 0, y: 2 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.15 }}
            className={
              line.tone === "accent" ? "text-emerald-400" : line.tone === "muted" ? "text-zinc-500" : "text-zinc-200"
            }
          >
            {line.text}
          </motion.p>
        ))}
      </div>
    </div>
  );
}
