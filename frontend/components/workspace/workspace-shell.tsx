"use client";

import { useCallback, useEffect, useLayoutEffect, useState, type ReactNode } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// Below this width, three side-by-side panes have no room left to be
// useful (see the tabbed-view branch further down, which replaces what
// used to be an "auto-collapse just the right/chat pane" behavior at this
// same breakpoint). Matches Tailwind's default "lg" breakpoint.
const NARROW_BREAKPOINT_PX = 1024;

const LEFT_WIDTH_DEFAULT = 280;
const LEFT_WIDTH_MIN = 200;
const LEFT_WIDTH_MAX = 450;
const RIGHT_WIDTH_DEFAULT = 380;
const RIGHT_WIDTH_MIN = 320;
const RIGHT_WIDTH_MAX = 600;
// Whatever the left/right panes get resized to, the center code-viewer
// pane must always keep at least this much room -- each resize handle
// clamps against it using the live viewport width, on top of its own
// pane's min/max bounds.
const MIN_CENTER_WIDTH_PX = 240;

const LEFT_WIDTH_STORAGE_KEY = "workspace-shell:left-width";
const RIGHT_WIDTH_STORAGE_KEY = "workspace-shell:right-width";

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

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

// A pane's width starts at its fixed default on every render -- including
// the server render and the very first client render before hydration --
// and only swaps in a `localStorage`-remembered value afterward, via
// effect. This deliberately does not read `localStorage` synchronously
// during render: that would need its own `typeof window` guard just to
// avoid crashing on the server, and would still risk a hydration mismatch
// since the server has no `localStorage` to read from at all. First paint
// always matches the default (so it never blocks initial render), and a
// user's remembered width -- if any -- pops in a moment after mount. Same
// "SSR-safe, client-hydrated" shape as `useJobPolling` and
// `code-viewer.tsx` elsewhere in this codebase.
//
// The returned setter writes to `localStorage` itself, inline with the
// state update, instead of a second effect watching `width` and persisting
// on every change. That second-effect shape looks natural but has a real
// bug under React 18 Strict Mode's dev-only double-invocation of mount
// effects: on the first mount, the hydration effect and a naive persist
// effect both run twice back-to-back *before* the hydrated value has
// committed as a new render, so the persist effect's first pass -- still
// seeing the pre-hydration default in `width` -- writes that default over
// whatever was actually stored, and the hydration effect's second pass
// then reads back its own just-corrupted value. Writing only from the
// setter (i.e. only in direct response to an actual drag) sidesteps this
// entirely: nothing but a real width change ever touches storage.
function usePersistedWidth(
  storageKey: string,
  defaultWidth: number,
  min: number,
  max: number
): readonly [number, (updater: number | ((prev: number) => number)) => void] {
  const [width, setWidthState] = useState(defaultWidth);

  // useLayoutEffect, not useEffect: confirmed live (real browser, not just
  // reasoning about it) that a passive effect here is too late -- framer-
  // motion's `motion.aside` (the consumer of this width, in the component
  // below) had already established its animated width at the pre-hydration
  // default by the time a useEffect-driven correction landed, and never
  // picked up the later change, leaving the pane visibly stuck at the
  // default width forever despite `localStorage` holding the right value.
  // Synchronous-before-paint via useLayoutEffect avoids that race.
  useLayoutEffect(() => {
    const stored = window.localStorage.getItem(storageKey);
    if (stored === null) return;
    const parsed = Number(stored);
    if (!Number.isNaN(parsed)) setWidthState(clamp(parsed, min, max));
    // Intentionally mount-only: this hydrates the one-time remembered
    // value. It must not re-run later and clobber a live drag in progress.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setWidth = useCallback(
    (updater: number | ((prev: number) => number)) => {
      setWidthState((prev) => {
        const next = typeof updater === "function" ? (updater as (prev: number) => number)(prev) : updater;
        window.localStorage.setItem(storageKey, String(next));
        return next;
      });
    },
    [storageKey]
  );

  return [width, setWidth] as const;
}

// A thin draggable divider between two panes. Pointer movement is tracked
// directly via `mousemove`/`mouseup` listeners on `window` (attached only
// for the duration of a drag) rather than e.g. framer-motion's drag
// gesture, so the caller's width state -- and therefore the pane's
// rendered width -- updates in lockstep with the mouse with no animation
// lag; `WorkspaceShell` separately suppresses the panes' open/close spring
// transition while a drag is in progress (see `draggingPane` below) so
// those live width changes aren't smoothed/delayed on top of that.
function ResizeHandle({
  ariaLabel,
  onDragStart,
  onDrag,
  onDragEnd,
}: {
  ariaLabel: string;
  onDragStart: () => void;
  onDrag: (deltaX: number) => void;
  onDragEnd: () => void;
}) {
  function handleMouseDown(e: React.MouseEvent<HTMLDivElement>) {
    e.preventDefault();
    onDragStart();
    let lastX = e.clientX;

    function handleMouseMove(moveEvent: MouseEvent) {
      const deltaX = moveEvent.clientX - lastX;
      lastX = moveEvent.clientX;
      onDrag(deltaX);
    }
    function handleMouseUp() {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
      onDragEnd();
    }

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
  }

  return (
    <div
      role="separator"
      aria-label={ariaLabel}
      aria-orientation="vertical"
      onMouseDown={handleMouseDown}
      className="group relative z-10 w-1.5 shrink-0 cursor-col-resize touch-none select-none"
    >
      <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-zinc-800/60 transition-colors group-hover:bg-primary/60 group-active:bg-primary" />
    </div>
  );
}

type TabKey = "files" | "code" | "chat";
const TABS: { key: TabKey; icon: string; label: string }[] = [
  { key: "files", icon: "\u{1F4C1}", label: "Files" },
  { key: "code", icon: "\u{1F4C4}", label: "Code" },
  { key: "chat", icon: "\u{1F4AC}", label: "AI Assistant" },
];

// Segmented tab control for the sub-1024px layout below -- visually matches
// `ViewModeToggle` in code-viewer.tsx exactly (a `role="tablist"`/
// `role="tab"` segmented control with a `layoutId`-based sliding highlight
// pill, same `duration: 0.2, ease: "easeInOut"` transition) rather than
// inventing a second tab style for this codebase.
function WorkspaceTabs({ active, onChange }: { active: TabKey; onChange: (tab: TabKey) => void }) {
  return (
    <div
      role="tablist"
      aria-label="Workspace view"
      className="glass relative m-2 flex shrink-0 items-center gap-0.5 rounded-full p-0.5"
    >
      {TABS.map((tab) => (
        <button
          key={tab.key}
          type="button"
          role="tab"
          aria-selected={active === tab.key}
          onClick={() => onChange(tab.key)}
          className={cn(
            "relative flex-1 rounded-full px-2.5 py-1.5 text-xs font-medium transition-colors",
            active === tab.key ? "text-zinc-950" : "text-zinc-400 hover:text-zinc-200"
          )}
        >
          {active === tab.key && (
            <motion.span
              layoutId="workspace-tab-pill"
              className="absolute inset-0 -z-10 rounded-full bg-primary shadow-[0_0_10px_-1px_hsl(var(--primary)/0.55)]"
              transition={{ duration: 0.2, ease: "easeInOut" }}
            />
          )}
          <span className="whitespace-nowrap">
            {tab.icon} {tab.label}
          </span>
        </button>
      ))}
    </div>
  );
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
  const [activeTab, setActiveTab] = useState<TabKey>("files");
  // Suppresses the panes' `transition` (their open/close spring) while a
  // resize drag is in progress, so live width updates track the mouse with
  // no animation lag -- see `ResizeHandle`'s comment. Restored to the
  // normal eased transition the instant the drag ends.
  const [draggingPane, setDraggingPane] = useState<"left" | "right" | null>(null);

  const isNarrow = useIsNarrowViewport(NARROW_BREAKPOINT_PX);

  const [leftWidth, setLeftWidth] = usePersistedWidth(
    LEFT_WIDTH_STORAGE_KEY,
    LEFT_WIDTH_DEFAULT,
    LEFT_WIDTH_MIN,
    LEFT_WIDTH_MAX
  );
  const [rightWidth, setRightWidth] = usePersistedWidth(
    RIGHT_WIDTH_STORAGE_KEY,
    RIGHT_WIDTH_DEFAULT,
    RIGHT_WIDTH_MIN,
    RIGHT_WIDTH_MAX
  );

  const handleLeftDrag = useCallback(
    (deltaX: number) => {
      setLeftWidth((prev) => {
        let next = clamp(prev + deltaX, LEFT_WIDTH_MIN, LEFT_WIDTH_MAX);
        if (rightOpen) {
          const maxAvailable = window.innerWidth - rightWidth - MIN_CENTER_WIDTH_PX;
          next = Math.min(next, Math.max(LEFT_WIDTH_MIN, maxAvailable));
        }
        return next;
      });
    },
    [rightOpen, rightWidth, setLeftWidth]
  );

  const handleRightDrag = useCallback(
    (deltaX: number) => {
      setRightWidth((prev) => {
        let next = clamp(prev - deltaX, RIGHT_WIDTH_MIN, RIGHT_WIDTH_MAX);
        if (leftOpen) {
          const maxAvailable = window.innerWidth - leftWidth - MIN_CENTER_WIDTH_PX;
          next = Math.min(next, Math.max(RIGHT_WIDTH_MIN, maxAvailable));
        }
        return next;
      });
    },
    [leftOpen, leftWidth, setRightWidth]
  );

  const paneTransition = draggingPane ? { duration: 0 } : { duration: 0.2, ease: "easeInOut" as const };

  if (isNarrow) {
    // Below the breakpoint, three side-by-side panes have no room to be
    // useful -- replaced entirely by a single-pane tabbed view (this used
    // to just auto-collapse the right/chat pane and keep a cramped 2-pane
    // layout instead) so exactly one of Files/Code/AI Assistant is visible
    // at a time, switched via the tab bar below.
    return (
      <div className="flex min-h-0 w-full flex-1 flex-col overflow-hidden">
        <WorkspaceTabs active={activeTab} onChange={setActiveTab} />
        <div className="min-h-0 min-w-0 flex-1 overflow-y-auto scrollbar-thin">
          {activeTab === "files" && left}
          {activeTab === "code" && center}
          {activeTab === "chat" && right}
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 w-full flex-1 overflow-hidden">
      <AnimatePresence initial={false}>
        {leftOpen && (
          <motion.aside
            key="left"
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: leftWidth, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={paneTransition}
            className="shrink-0 overflow-hidden border-r border-zinc-800/60 bg-white/[0.03] backdrop-blur-xl"
          >
            <div className="h-full overflow-y-auto scrollbar-thin" style={{ width: leftWidth }}>
              {left}
            </div>
          </motion.aside>
        )}
      </AnimatePresence>

      {leftOpen && (
        <ResizeHandle
          ariaLabel="Resize file tree panel"
          onDragStart={() => setDraggingPane("left")}
          onDrag={handleLeftDrag}
          onDragEnd={() => setDraggingPane(null)}
        />
      )}

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

      {rightOpen && (
        <ResizeHandle
          ariaLabel="Resize chat panel"
          onDragStart={() => setDraggingPane("right")}
          onDrag={handleRightDrag}
          onDragEnd={() => setDraggingPane(null)}
        />
      )}

      <AnimatePresence initial={false}>
        {rightOpen && (
          <motion.aside
            key="right"
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: rightWidth, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={paneTransition}
            className="shrink-0 overflow-hidden border-l border-zinc-800/60 bg-white/[0.03] backdrop-blur-xl"
          >
            <div className="h-full" style={{ width: rightWidth }}>
              {right}
            </div>
          </motion.aside>
        )}
      </AnimatePresence>
    </div>
  );
}
