"use client";

import { useState, type ReactNode } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from "lucide-react";
import { Button } from "@/components/ui/button";

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
            className="shrink-0 overflow-hidden border-r border-border"
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
            className="shrink-0 overflow-hidden border-l border-border"
          >
            <div className="h-full w-[380px]">{right}</div>
          </motion.aside>
        )}
      </AnimatePresence>
    </div>
  );
}
