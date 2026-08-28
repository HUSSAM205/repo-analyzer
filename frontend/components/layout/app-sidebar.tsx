"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import {
  ChevronDown,
  ChevronsLeft,
  ChevronsRight,
  FileBarChart2,
  FolderGit2,
  History,
  Loader2,
  Menu,
  MessageCircleQuestion,
  MessageSquare,
  Settings as SettingsIcon,
  Wrench,
  X,
} from "lucide-react";
import { apiFetch } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import { FlagshipToolsModal } from "@/components/workspace/flagship-tools-modal";
import { ReportsModal } from "@/components/workspace/reports-modal";
import { FeedbackModal } from "@/components/feedback-modal";
import { GeometricLogo } from "./geometric-logo";
import type { Repo } from "@/lib/types";

const COLLAPSE_STORAGE_KEY = "sidebar:collapsed";
const REPO_ID_PATTERN = /^\/repos\/([0-9a-fA-F-]{8,})/;

function useActiveRepoId(): string | null {
  const pathname = usePathname();
  const match = pathname.match(REPO_ID_PATTERN);
  return match ? match[1] : null;
}

function usePersistedCollapsed(): [boolean, (value: boolean) => void] {
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    try {
      setCollapsed(window.localStorage.getItem(COLLAPSE_STORAGE_KEY) === "1");
    } catch {
      // Private-browsing/storage-blocked -- default (expanded) is fine.
    }
  }, []);
  const update = (value: boolean) => {
    setCollapsed(value);
    try {
      window.localStorage.setItem(COLLAPSE_STORAGE_KEY, value ? "1" : "0");
    } catch {
      // Nothing to persist to -- the in-memory state above still works for
      // the rest of this session.
    }
  };
  return [collapsed, update];
}

const NAV_BUTTON_CLASSES = (collapsed: boolean, active: boolean | undefined, disabled: boolean | undefined) =>
  cn(
    "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
    collapsed && "justify-center px-0",
    active
      ? "bg-primary text-primary-foreground"
      : "text-muted-foreground hover:bg-accent hover:text-foreground",
    disabled && "cursor-not-allowed opacity-40 hover:bg-transparent hover:text-muted-foreground"
  );

// Renders as a real <Link> when `href` is given (so it behaves like normal
// navigation -- middle-click/open-in-new-tab, no full reload) or a plain
// <button> otherwise (modal triggers) -- never a <button> nested inside a
// <Link>'s <a>, which is invalid HTML and breaks click handling in some
// browsers.
function NavButton({
  icon: Icon,
  label,
  collapsed,
  active,
  disabled,
  href,
  onClick,
}: {
  icon: typeof MessageSquare;
  label: string;
  collapsed: boolean;
  active?: boolean;
  disabled?: boolean;
  href?: string;
  onClick?: () => void;
}) {
  const content = (
    <>
      <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
      {!collapsed && <span className="truncate">{label}</span>}
    </>
  );
  const title = collapsed ? label : disabled ? "Open a repository first" : undefined;

  if (href) {
    return (
      <Link href={href} onClick={onClick} title={title} className={NAV_BUTTON_CLASSES(collapsed, active, disabled)}>
        {content}
      </Link>
    );
  }

  return (
    <button type="button" onClick={onClick} disabled={disabled} title={title} className={NAV_BUTTON_CLASSES(collapsed, active, disabled)}>
      {content}
    </button>
  );
}

function SectionLabel({ children, collapsed }: { children: string; collapsed: boolean }) {
  if (collapsed) return <div className="my-2 border-t border-zinc-800/60" />;
  return (
    <p className="mb-1 mt-4 px-3 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/70">
      {children}
    </p>
  );
}

function PastReposSection({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const [repos, setRepos] = useState<Repo[] | null>(null);

  useEffect(() => {
    if (!expanded || repos !== null) return;
    apiFetch("/api/repos", { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : []))
      .then((data: Repo[]) => setRepos(data))
      .catch(() => setRepos([]));
  }, [expanded, repos]);

  if (collapsed) {
    return (
      <Link
        href="/repos"
        title="Past Analyzed Repos"
        onClick={onNavigate}
        className="flex w-full items-center justify-center rounded-md px-0 py-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
      >
        <History className="h-4 w-4" aria-hidden="true" />
      </Link>
    );
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
      >
        <History className="h-4 w-4 shrink-0" aria-hidden="true" />
        <span className="flex-1 truncate text-left">Past Analyzed Repos</span>
        <ChevronDown className={cn("h-3.5 w-3.5 shrink-0 transition-transform", expanded && "rotate-180")} aria-hidden="true" />
      </button>
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="overflow-hidden"
          >
            <div className="ml-4 mt-1 space-y-0.5 border-l border-zinc-800/60 pl-3">
              {repos === null ? (
                <div className="flex items-center gap-2 py-1.5 text-xs text-muted-foreground">
                  <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
                  Loading...
                </div>
              ) : repos.length === 0 ? (
                <p className="py-1.5 text-xs text-muted-foreground">No repositories yet.</p>
              ) : (
                <>
                  {repos.slice(0, 6).map((r) => (
                    <Link
                      key={r.id}
                      href={`/repos/${r.id}`}
                      onClick={onNavigate}
                      className="block truncate rounded px-2 py-1 font-mono text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                    >
                      {r.name}
                    </Link>
                  ))}
                  <Link
                    href="/repos"
                    onClick={onNavigate}
                    className="block px-2 py-1 text-xs font-medium text-primary hover:underline"
                  >
                    View all
                  </Link>
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function SidebarContent({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const pathname = usePathname();
  const repoId = useActiveRepoId();
  const [toolsOpen, setToolsOpen] = useState(false);
  const [reportsOpen, setReportsOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);

  return (
    <div className="flex h-full flex-col">
      <Link
        href="/repos"
        onClick={onNavigate}
        className={cn("flex items-center gap-2.5 px-4 pb-2 pt-4", collapsed && "justify-center px-0")}
      >
        <GeometricLogo className="h-7 w-7 shrink-0 text-primary" />
        {!collapsed && (
          <div className="min-w-0">
            <p className="truncate font-mono text-sm font-bold tracking-tight text-foreground">RepoLens AI</p>
            <p className="mt-0.5 block whitespace-normal text-[11px] font-normal leading-tight text-muted-foreground">
              Powered &amp; Managed by Easy Solutions
            </p>
          </div>
        )}
      </Link>

      <nav className="min-h-0 flex-1 overflow-y-auto scrollbar-thin px-2 pb-4">
        <SectionLabel collapsed={collapsed}>Core</SectionLabel>
        <div className="space-y-0.5">
          <NavButton
            icon={MessageSquare}
            label="AI Chatbot"
            collapsed={collapsed}
            disabled={!repoId}
            href={repoId ? `/repos/${repoId}?tab=chat` : undefined}
            onClick={onNavigate}
          />
          <NavButton
            icon={FolderGit2}
            label="Repos"
            collapsed={collapsed}
            active={pathname === "/repos"}
            href="/repos"
            onClick={onNavigate}
          />
          <NavButton
            icon={Wrench}
            label="Tools"
            collapsed={collapsed}
            disabled={!repoId}
            onClick={() => repoId && setToolsOpen(true)}
          />
          <PastReposSection collapsed={collapsed} onNavigate={onNavigate} />
        </div>

        <SectionLabel collapsed={collapsed}>Management</SectionLabel>
        <div className="space-y-0.5">
          <NavButton icon={MessageCircleQuestion} label="Feedback" collapsed={collapsed} onClick={() => setFeedbackOpen(true)} />
          <NavButton
            icon={FileBarChart2}
            label="Reports"
            collapsed={collapsed}
            disabled={!repoId}
            onClick={() => repoId && setReportsOpen(true)}
          />
          <NavButton
            icon={SettingsIcon}
            label="Settings"
            collapsed={collapsed}
            active={pathname === "/settings"}
            href="/settings"
            onClick={onNavigate}
          />
        </div>
      </nav>

      {repoId && toolsOpen && <FlagshipToolsModal repoId={repoId} onClose={() => setToolsOpen(false)} />}
      {repoId && reportsOpen && <ReportsModal repoId={repoId} onClose={() => setReportsOpen(false)} />}
      {feedbackOpen && <FeedbackModal onClose={() => setFeedbackOpen(false)} />}
    </div>
  );
}

export function AppSidebar() {
  const [collapsed, setCollapsed] = usePersistedCollapsed();
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <>
      {/* Mobile trigger -- floats above AppHeader, only visible below `lg`. */}
      <button
        type="button"
        aria-label="Open navigation menu"
        onClick={() => setMobileOpen(true)}
        className="glass fixed left-3 top-3 z-[60] flex h-9 w-9 items-center justify-center rounded-md text-foreground lg:hidden"
      >
        <Menu className="h-5 w-5" aria-hidden="true" />
      </button>

      {/* Desktop rail. overflow-hidden lives on the inner wrapper, not the
          <aside> itself, so the collapse toggle below (deliberately
          straddling the right edge at -right-3) stays fully visible instead
          of getting clipped by it. */}
      <aside
        className={cn(
          "panel-glow relative hidden shrink-0 border-r border-border bg-card/40 transition-[width] duration-200 lg:flex",
          collapsed ? "w-16" : "w-72"
        )}
      >
        <div className="h-full w-full overflow-hidden">
          <SidebarContent collapsed={collapsed} />
        </div>
        <button
          type="button"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          onClick={() => setCollapsed(!collapsed)}
          className="glass absolute -right-3 top-6 flex h-6 w-6 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground"
        >
          {collapsed ? <ChevronsRight className="h-3.5 w-3.5" /> : <ChevronsLeft className="h-3.5 w-3.5" />}
        </button>
      </aside>

      {/* Mobile drawer. */}
      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="fixed inset-0 z-[70] bg-black/60 backdrop-blur-sm lg:hidden"
            onClick={() => setMobileOpen(false)}
          >
            <motion.div
              initial={{ x: "-100%" }}
              animate={{ x: 0 }}
              exit={{ x: "-100%" }}
              transition={{ duration: 0.2, ease: "easeOut" }}
              onClick={(e) => e.stopPropagation()}
              className="h-full w-72 max-w-[80vw] border-r border-border bg-card"
            >
              <div className="flex justify-end p-2">
                <button
                  type="button"
                  aria-label="Close navigation menu"
                  onClick={() => setMobileOpen(false)}
                  className="rounded-md p-1.5 text-muted-foreground hover:text-foreground"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <SidebarContent collapsed={false} onNavigate={() => setMobileOpen(false)} />
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
