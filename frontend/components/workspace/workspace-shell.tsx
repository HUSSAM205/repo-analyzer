"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from "lucide-react";
import { Button } from "@/components/ui/button";

// Below this width the ~660px of combined fixed-width sidebar chrome
// (280px + 380px) squeezes the center code-viewer pane to an unusable
// width. Matches Tailwind's default "lg" breakpoint.
const NARROW_BREAKPOINT_PX = 1024;

// Plain `window.innerWidth` + a "resize" listener rather than
// `matchMedia`: jsdom (this project's Jest test environment) doesn't
// implement `matchMedia` at all, while `window.innerWidth` and dispatched
// "resize" events work out of the box there, so this stays testable
// without adding a jsdom polyfill.
function useIsNarrowViewport(breakpointPx: number): boolean {
  const [isNarrow, setIsNarrow] = useState(
    () => typeof window !== "undefined" && window.innerWidth < breakpointPx
  );

  useEffect(() => {
    function handleResize() {
      setIsNarrow(window.innerWidth < breakpointPx);
    }
    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [breakpointPx]);

  return isNarrow;
}

export function WorkspaceShell({
  left,
  center,
  right,
}: {
  left: ReactNode;
  center: ReactNode;
  right: ReactNode;
}) {
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);

  const isNarrow = useIsNarrowViewport(NARROW_BREAKPOINT_PX);

  // Auto-collapse the chat panel (the right sidebar) the moment the
  // viewport crosses below the breakpoint, without fighting the manual
  // toggle buttons afterward: this only forces the closed state once per
  // narrow-entry transition (including an initial mount that's already
  // narrow), so a user who manually reopens it back stays open until the
  // viewport widens past the breakpoint and narrows again.
  const wasNarrowRef = useRef(false);
  useEffect(() => {
    if (isNarrow && !wasNarrowRef.current) {
      setRightOpen(false);
    }
    wasNarrowRef.current = isNarrow;
  }, [isNarrow]);

  return (
    <div className="flex min-h-0 w-full flex-1 overflow-hidden">
      <AnimatePresence initial={false}>
        {leftOpen && (
          <motion.aside
            key="left"
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: 280, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: "easeInOut" }}
            className="shrink-0 overflow-hidden border-r border-zinc-800/60 bg-white/[0.03] backdrop-blur-xl"
          >
            <div className="h-full w-[280px] overflow-y-auto scrollbar-thin">{left}</div>
          </motion.aside>
        )}
      </AnimatePresence>

      <div className="relative flex min-w-0 flex-1 flex-col">
        <div className="absolute left-2 top-2 z-10">
          <Button variant="ghost" size="icon" onClick={() => setLeftOpen((v) => !v)} aria-label="Toggle file tree">
            {leftOpen ? <PanelLeftClose className="h-4 w-4" /> : <PanelLeftOpen className="h-4 w-4" />}
          </Button>
        </div>
        <div className="absolute right-2 top-2 z-10">
          <Button variant="ghost" size="icon" onClick={() => setRightOpen((v) => !v)} aria-label="Toggle chat panel">
            {rightOpen ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto scrollbar-thin">{center}</div>
      </div>

      <AnimatePresence initial={false}>
        {rightOpen && (
          <motion.aside
            key="right"
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: 380, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: "easeInOut" }}
            className="shrink-0 overflow-hidden border-l border-zinc-800/60 bg-white/[0.03] backdrop-blur-xl"
          >
            <div className="h-full w-[380px]">{right}</div>
          </motion.aside>
        )}
      </AnimatePresence>
    </div>
  );
}
