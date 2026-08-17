"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronRight, File, Folder } from "lucide-react";
import { cn } from "@/lib/utils";
import type { FileTreeEntry } from "@/lib/types";

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
    return (
      <button
        type="button"
        onClick={() => onSelectFile(entry.path)}
        style={{ paddingLeft: `${depth * 14 + 8}px` }}
        className={cn(
          "flex w-full items-center gap-1.5 rounded-sm py-1 text-left text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground",
          selectedPath === entry.path && "bg-accent text-foreground"
        )}
      >
        <File className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate font-mono text-xs">{entry.name}</span>
      </button>
    );
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
