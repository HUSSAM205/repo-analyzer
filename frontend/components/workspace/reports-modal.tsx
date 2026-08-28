"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Boxes, FileBarChart2, Network, Scale, Waypoints, X } from "lucide-react";
import { CompliancePanel } from "./compliance-panel";
import { RouteExplorerPanel } from "./route-explorer-panel";
import { ModuleMapViewer } from "./module-map-viewer";
import { FlowMapViewer } from "./flow-map-viewer";
import { cn } from "@/lib/utils";

type ReportKey = "compliance" | "routes" | "modulemap" | "flowmap";

const REPORTS: { key: ReportKey; label: string; icon: typeof FileBarChart2 }[] = [
  { key: "compliance", label: "Compliance & Licenses", icon: Scale },
  { key: "routes", label: "API Explorer", icon: Boxes },
  { key: "modulemap", label: "Module Map", icon: Network },
  { key: "flowmap", label: "Flow Map", icon: Waypoints },
];

// A focused view onto just the four exportable flagship tools -- each of
// these panels already has its own ExportMenu (Markdown/JSON/OpenAPI/SVG/
// PNG, see export-menu.tsx) wired in; this modal only exists so "Reports"
// in the sidebar doesn't require digging through the full 13-tool
// FlagshipToolsModal to find the ones that actually produce a downloadable
// artifact.
export function ReportsModal({ repoId, onClose }: { repoId: string; onClose: () => void }) {
  const [active, setActive] = useState<ReportKey>("compliance");

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
          aria-label="Reports"
          initial={{ opacity: 0, scale: 0.96, y: 8 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.96, y: 8 }}
          transition={{ duration: 0.18, ease: "easeOut" }}
          onClick={(e) => e.stopPropagation()}
          className="glass flex h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-border shadow-2xl"
        >
          <div className="flex shrink-0 items-center justify-between border-b border-border px-4 py-3">
            <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
              <FileBarChart2 className="h-4 w-4 text-primary" aria-hidden="true" />
              Reports
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

          <div role="tablist" aria-label="Reports" className="flex shrink-0 gap-1 overflow-x-auto border-b border-border p-2">
            {REPORTS.map((report) => (
              <button
                key={report.key}
                type="button"
                role="tab"
                aria-selected={active === report.key}
                onClick={() => setActive(report.key)}
                className={cn(
                  "relative flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
                  active === report.key ? "text-zinc-950" : "text-muted-foreground hover:text-foreground"
                )}
              >
                {active === report.key && (
                  <motion.span
                    layoutId="reports-tab-pill"
                    className="absolute inset-0 -z-10 rounded-full bg-primary shadow-[0_0_10px_-1px_hsl(var(--primary)/0.55)]"
                    transition={{ duration: 0.2, ease: "easeInOut" }}
                  />
                )}
                <report.icon className="h-3.5 w-3.5" aria-hidden="true" />
                {report.label}
              </button>
            ))}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto scrollbar-thin">
            {active === "compliance" && <CompliancePanel repoId={repoId} />}
            {active === "routes" && <RouteExplorerPanel repoId={repoId} />}
            {active === "modulemap" && <ModuleMapViewer repoId={repoId} />}
            {active === "flowmap" && <FlowMapViewer repoId={repoId} />}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
