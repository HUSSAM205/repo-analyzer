"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  Boxes,
  Brain,
  Container,
  FileText,
  Gauge,
  Network,
  Regex,
  Rocket,
  Scale,
  ShieldAlert,
  Waypoints,
  Wrench,
  X,
} from "lucide-react";
import { ReadmeGenerator } from "./readme-generator";
import { SecurityScanner } from "./security-scanner";
import { HealthScorecard } from "./health-scorecard";
import { QuickStartGuide } from "./quick-start-guide";
import { KnowledgeQuiz } from "./knowledge-quiz";
import { FlowMapViewer } from "./flow-map-viewer";
import { TechDebtPanel } from "./tech-debt-panel";
import { CompliancePanel } from "./compliance-panel";
import { RouteExplorerPanel } from "./route-explorer-panel";
import { ModuleMapViewer } from "./module-map-viewer";
import { BootstrapPanel } from "./bootstrap-panel";
import { ComplexityRadarPanel } from "./complexity-radar-panel";
import { RegexPlayground } from "./regex-playground";
import { cn } from "@/lib/utils";

type ToolKey =
  | "quickstart"
  | "readme"
  | "scan"
  | "health"
  | "quiz"
  | "flowmap"
  | "modulemap"
  | "routes"
  | "bootstrap"
  | "complexity"
  | "regex"
  | "techdebt"
  | "compliance";

const TOOLS: { key: ToolKey; label: string; icon: typeof FileText }[] = [
  { key: "quickstart", label: "Quick Start", icon: Rocket },
  { key: "readme", label: "Docs Generator", icon: FileText },
  { key: "scan", label: "Bug & Security Scan", icon: ShieldAlert },
  { key: "health", label: "Health Score", icon: Activity },
  { key: "quiz", label: "Knowledge Quiz", icon: Brain },
  { key: "flowmap", label: "Flow Map", icon: Waypoints },
  { key: "modulemap", label: "Module Map", icon: Network },
  { key: "routes", label: "API Explorer", icon: Boxes },
  { key: "bootstrap", label: "Bootstrapper", icon: Container },
  { key: "complexity", label: "Complexity Radar", icon: Gauge },
  { key: "regex", label: "Regex Playground", icon: Regex },
  { key: "techdebt", label: "Tech Debt & ROI", icon: Wrench },
  { key: "compliance", label: "Compliance & Licenses", icon: Scale },
];

export function FlagshipToolsModal({ repoId, onClose }: { repoId: string; onClose: () => void }) {
  const [active, setActive] = useState<ToolKey>("quickstart");

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.15 }}
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
        onClick={onClose}
      >
        <motion.div
          role="dialog"
          aria-modal="true"
          aria-label="Flagship tools"
          initial={{ opacity: 0, scale: 0.96, y: 8 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.96, y: 8 }}
          transition={{ duration: 0.18, ease: "easeOut" }}
          onClick={(e) => e.stopPropagation()}
          className="glass flex h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-border shadow-2xl"
        >
          <div className="flex shrink-0 items-center justify-between border-b border-border px-4 py-3">
            <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
              <Wrench className="h-4 w-4 text-primary" aria-hidden="true" />
              Flagship Tools
            </span>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="rounded-md p-1 text-muted-foreground transition-colors hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div role="tablist" aria-label="Flagship tools" className="flex shrink-0 gap-1 overflow-x-auto border-b border-border p-2">
            {TOOLS.map((tool) => (
              <button
                key={tool.key}
                type="button"
                role="tab"
                aria-selected={active === tool.key}
                onClick={() => setActive(tool.key)}
                className={cn(
                  "relative flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
                  active === tool.key ? "text-zinc-950" : "text-muted-foreground hover:text-foreground"
                )}
              >
                {active === tool.key && (
                  <motion.span
                    layoutId="flagship-tool-pill"
                    className="absolute inset-0 -z-10 rounded-full bg-primary shadow-[0_0_10px_-1px_hsl(var(--primary)/0.55)]"
                    transition={{ duration: 0.2, ease: "easeInOut" }}
                  />
                )}
                <tool.icon className="h-3.5 w-3.5" aria-hidden="true" />
                {tool.label}
              </button>
            ))}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto scrollbar-thin">
            {active === "quickstart" && <QuickStartGuide repoId={repoId} />}
            {active === "readme" && <ReadmeGenerator repoId={repoId} />}
            {active === "scan" && <SecurityScanner repoId={repoId} />}
            {active === "health" && <HealthScorecard repoId={repoId} />}
            {active === "quiz" && <KnowledgeQuiz repoId={repoId} />}
            {active === "flowmap" && <FlowMapViewer repoId={repoId} />}
            {active === "modulemap" && <ModuleMapViewer repoId={repoId} />}
            {active === "routes" && <RouteExplorerPanel repoId={repoId} />}
            {active === "bootstrap" && <BootstrapPanel repoId={repoId} />}
            {active === "complexity" && <ComplexityRadarPanel repoId={repoId} />}
            {active === "regex" && <RegexPlayground />}
            {active === "techdebt" && <TechDebtPanel repoId={repoId} />}
            {active === "compliance" && <CompliancePanel repoId={repoId} />}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
