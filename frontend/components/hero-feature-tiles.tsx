"use client";

import { motion } from "framer-motion";
import { TiltCard } from "@/components/tilt-card";

// Tiny animated node graph -- three "symbol" nodes linking back to a root,
// each pulsing in sequence. Illustrates AST-level structural mapping
// without claiming to be a literal rendering of any real repo's graph.
function AstMappingVisual() {
  const nodes = [
    { cx: 20, cy: 40 },
    { cx: 60, cy: 15 },
    { cx: 60, cy: 65 },
  ];
  return (
    <svg viewBox="0 0 80 80" className="h-16 w-full" aria-hidden="true">
      {nodes.map((n, i) => (
        <line key={i} x1={20} y1={40} x2={n.cx} y2={n.cy} stroke="hsl(var(--primary) / 0.35)" strokeWidth={1.5} />
      ))}
      <circle cx={20} cy={40} r={5} className="fill-primary" />
      {nodes.map((n, i) => (
        <motion.circle
          key={i}
          cx={n.cx}
          cy={n.cy}
          r={4}
          className="fill-primary"
          animate={{ opacity: [0.35, 1, 0.35] }}
          transition={{ duration: 1.8, repeat: Infinity, delay: i * 0.3, ease: "easeInOut" }}
        />
      ))}
    </svg>
  );
}

// A before/after token-count compression readout -- the actual, real
// mechanism this app uses (AST-chunk retrieval + a rolling conversation
// summary, see backend/app/core/agent_tools.py and conversation_summary.py)
// rather than a generic "fast chat" animation.
function TokenCompressionVisual() {
  return (
    <div className="flex h-16 w-full flex-col items-center justify-center gap-1.5 font-mono text-[11px]">
      <div className="flex items-center gap-2">
        <span className="text-muted-foreground line-through decoration-destructive/60">~12,400 tok</span>
        <motion.span
          className="text-primary"
          animate={{ x: [0, 3, 0] }}
          transition={{ duration: 1.2, repeat: Infinity, ease: "easeInOut" }}
        >
          →
        </motion.span>
        <span className="font-semibold text-emerald-500 dark:text-emerald-400">~640 tok</span>
      </div>
      <div className="h-1 w-3/4 overflow-hidden rounded-full bg-border/60">
        <motion.div
          className="h-full rounded-full bg-primary"
          initial={{ width: "100%" }}
          animate={{ width: "5%" }}
          transition={{ duration: 1.6, repeat: Infinity, repeatType: "reverse", ease: "easeInOut" }}
        />
      </div>
    </div>
  );
}

// Three small live-feeling metric badges, pulsing independently -- stands
// in for "always-on, zero-token" scanning without implying these exact
// numbers are pulled from a real scan (the actual Compliance/Security
// panels, reachable from Tools/Reports, show the genuine live figures).
function SecurityRadarVisual() {
  const metrics = [
    { label: "0 secrets", tone: "emerald" as const },
    { label: "A+ grade", tone: "primary" as const },
    { label: "12 routes", tone: "amber" as const },
  ];
  const toneClass = {
    emerald: "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
    primary: "border-primary/40 bg-primary/10 text-primary",
    amber: "border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400",
  };
  return (
    <div className="flex h-16 w-full flex-wrap items-center justify-center gap-1.5">
      {metrics.map((m, i) => (
        <motion.span
          key={m.label}
          className={`rounded-full border px-2 py-1 text-[10px] font-semibold ${toneClass[m.tone]}`}
          animate={{ scale: [1, 1.06, 1] }}
          transition={{ duration: 2, repeat: Infinity, delay: i * 0.4, ease: "easeInOut" }}
        >
          {m.label}
        </motion.span>
      ))}
    </div>
  );
}

const TILES = [
  {
    key: "ast",
    label: "AST Deep Mapping",
    detail: "Real tree-sitter parsing indexes every symbol, function, and structural relationship -- zero LLM tokens.",
    Visual: AstMappingVisual,
  },
  {
    key: "chat",
    label: "Token-Compressed Chat",
    detail: "Tiered AST-chunk retrieval and a rolling conversation summary keep every turn's context bounded.",
    Visual: TokenCompressionVisual,
  },
  {
    key: "security",
    label: "Security & Architectural Radar",
    detail: "Secret detection, dangerous-pattern scanning, and route/complexity mapping -- always on, never rate-limited.",
    Visual: SecurityRadarVisual,
  },
];

export function HeroFeatureTiles() {
  return (
    <div className="grid w-full grid-cols-1 gap-4 sm:grid-cols-3">
      {TILES.map((tile, i) => (
        <TiltCard
          key={tile.key}
          className="glow-pill glass relative overflow-hidden rounded-2xl border border-border/60 bg-white/60 p-4 text-left shadow-sm dark:bg-zinc-900/40 dark:shadow-none"
        >
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, delay: i * 0.08, ease: "easeOut" }}
          >
            <tile.Visual />
            <p className="mt-2 font-mono text-xs font-semibold text-foreground">{tile.label}</p>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{tile.detail}</p>
          </motion.div>
        </TiltCard>
      ))}
    </div>
  );
}
