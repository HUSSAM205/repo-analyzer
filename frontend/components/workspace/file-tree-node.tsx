"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronRight, File, FileCode2, FileJson, FileText, Folder } from "lucide-react";
import { cn } from "@/lib/utils";
import type { FileTreeEntry } from "@/lib/types";

const EXTENSION_TO_ICON: Record<string, [typeof File, string]> = {
  json: [FileJson, "json"],
  py: [FileCode2, "code"],
  js: [FileCode2, "code"],
  jsx: [FileCode2, "code"],
  ts: [FileCode2, "code"],
  tsx: [FileCode2, "code"],
  go: [FileCode2, "code"],
  java: [FileCode2, "code"],
  md: [FileText, "text"],
  yml: [FileText, "text"],
  yaml: [FileText, "text"],
};

function iconForFile(name: string): [typeof File, string] {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  return EXTENSION_TO_ICON[ext] ?? [File, "default"];
}

export function FileTreeNode({
  entry,
  depth,
  selectedPath,
  onSelectFile,
}: {
  entry: FileTreeEntry;
  depth: number;
  selectedPath: string | null;
  onSelectFile: (path: string) => void;
}) {
  const [expanded, setExpanded] = useState(depth === 0);

  if (entry.type === "file") {
    return (() => {
      const [Icon, iconKey] = iconForFile(entry.name);
      return (
        <button
          type="button"
          onClick={() => onSelectFile(entry.path)}
          style={{ paddingLeft: `${depth * 14 + 8}px` }}
          className={cn(
            "flex w-full items-center gap-1.5 rounded-sm border-l-2 border-transparent py-1 text-left text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground",
            selectedPath === entry.path && "elevated-ring border-primary bg-accent text-foreground"
          )}
        >
          <Icon data-testid={`file-icon-${iconKey}`} className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate font-mono text-xs">{entry.name}</span>
        </button>
      );
    })();
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        style={{ paddingLeft: `${depth * 14 + 8}px` }}
        className="flex w-full items-center gap-1.5 rounded-sm py-1 text-left text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
      >
        <motion.span animate={{ rotate: expanded ? 90 : 0 }} transition={{ duration: 0.15 }}>
          <ChevronRight className="h-3.5 w-3.5 shrink-0" />
        </motion.span>
        <Folder className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate font-mono text-xs">{entry.name}</span>
      </button>
      <AnimatePresence initial={false}>
        {expanded && entry.children && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="overflow-hidden"
          >
            {entry.children.map((child) => (
              <FileTreeNode
                key={child.path}
                entry={child}
                depth={depth + 1}
                selectedPath={selectedPath}
                onSelectFile={onSelectFile}
              />
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
