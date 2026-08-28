"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface ExportOption {
  label: string;
  onSelect: () => void | Promise<void>;
}

// A small dropdown, not Radix's DropdownMenu -- this project has no
// existing dropdown primitive (ConversationPicker uses a native <select>,
// the flagship tools use tabs), and pulling in a new dependency for one
// menu with 2-3 static items is disproportionate. Closes on outside click
// and Escape, which covers the real accessibility requirement without the
// extra weight.
export function ExportMenu({ options, label = "Export" }: { options: ExportOption[]; label?: string }) {
  const [open, setOpen] = useState(false);
  const [justSelected, setJustSelected] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    }
    function handleEscape(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [open]);

  async function handleSelect(option: ExportOption) {
    await option.onSelect();
    setJustSelected(option.label);
    setOpen(false);
    setTimeout(() => setJustSelected(null), 1500);
  }

  return (
    <div ref={containerRef} className="relative">
      <Button size="sm" variant="outline" onClick={() => setOpen((v) => !v)} aria-haspopup="menu" aria-expanded={open}>
        <Download className="mr-1 h-3.5 w-3.5" />
        {label}
        <ChevronDown className={cn("ml-1 h-3 w-3 transition-transform", open && "rotate-180")} />
      </Button>
      {open && (
        <div
          role="menu"
          aria-label={`${label} options`}
          className="glass absolute right-0 top-full z-20 mt-1 min-w-[180px] overflow-hidden rounded-md border border-zinc-800/60 py-1 shadow-xl"
        >
          {options.map((option) => (
            <button
              key={option.label}
              type="button"
              role="menuitem"
              onClick={() => handleSelect(option)}
              className="flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-xs text-muted-foreground transition-colors hover:bg-primary/10 hover:text-foreground"
            >
              {option.label}
              {justSelected === option.label && <Check className="h-3 w-3 text-emerald-400" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
