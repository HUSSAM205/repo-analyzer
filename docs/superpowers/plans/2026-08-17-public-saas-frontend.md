# Public SaaS Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the login wall from the actual product experience (invisible guest-session bootstrap replaces it), and reskin the whole app to a Linear/Raycast/Cursor-style dark SaaS aesthetic.

**Architecture:** A widened Next.js middleware becomes the single place a visitor's session is created — it mints a guest token via sub-project 3A's `POST /api/v1/auth/guest` the first time it sees a request with no session cookie, transparently, before any page renders. Every existing proxy route and `apiFetch` 401-redirect keeps working unchanged; they just always find a valid token now. The visual reskin retunes the existing CSS-custom-property color tokens to the requested zinc palette (pixel-identical to raw `zinc-*` classes, far smaller diff than rewriting every component's class list) and adds a small number of new components (`AppHeader`) and enhancements to existing ones (icons, themes, pills).

**Tech Stack:** Next.js 14 App Router, TypeScript, Tailwind CSS, Framer Motion, Shiki, Jest + React Testing Library.

**Spec:** `docs/superpowers/specs/2026-08-17-public-saas-frontend-design.md`

**Depends on:** Sub-project 3A (`docs/superpowers/plans/2026-08-17-public-access-gemini.md`) must be complete and merged before this plan starts — specifically `POST /api/v1/auth/guest` (Task 1) and `GET /api/v1/repos/{repo_id}` (Task 2) are both consumed directly by Task 1 and Task 2 of this plan.

## Global Constraints

- No backend changes in this plan — everything here consumes 3A's API as-is.
- Desktop/laptop responsive only — no phone layout, same standing constraint as sub-project 2B.
- No account system, no "claim this guest session" UI, no user settings/profile — there is no user-identity concept exposed in the UI at all after this plan. The backend's register/login endpoints stay untouched and unused by this UI.
- The GitHub Star/Fork link target is a placeholder: `NEXT_PUBLIC_GITHUB_REPO_URL`, hidden/inert if unset — never a guessed or fabricated URL.
- Inter (sans) and JetBrains Mono (mono) are already wired via `next/font/google` in `app/layout.tsx` — this plan does not touch fonts.
- `npm run build` (equivalently `next build`) must complete with zero TypeScript and zero ESLint errors before this plan is done — verified per-task via `npx tsc --noEmit` and `npx next lint`, not deferred to one final step.
- The existing Playwright suite (`frontend/tests/e2e/full-flow.spec.ts`) already carries a known, pre-existing gap from sub-project 2B's merge (its local fixture-git server can't satisfy the backend's shallow clone) — not this plan's to fix. Don't mistake that still-red suite for a regression this plan introduced.

---

### Task 1: Guest-session bootstrap; remove login/register

**Files:**
- Create: `frontend/middleware.test.ts`
- Modify: `frontend/middleware.ts` (full rewrite)
- Delete: `frontend/app/(auth)/login/page.tsx`, `frontend/app/(auth)/login/page.test.tsx`, `frontend/app/(auth)/register/page.tsx`, `frontend/app/(auth)/register/page.test.tsx`, `frontend/app/api/auth/login/route.ts`, `frontend/app/api/auth/register/route.ts`
- Modify: `frontend/app/page.tsx` (landing redirect)
- Modify: `frontend/app/repos/page.tsx` (drop the now-dead `/login` redirects)
- Delete: `frontend/components/workspace/repo-header.test.tsx` (entirely about the sign-out button, which Task 2 removes — deleting it here since Task 1 is what makes `/login` stop existing, and leaving a test that still asserts a redirect to a now-deleted page would be actively wrong the moment this task lands, even before Task 2 removes the button itself)

**Interfaces:**
- Produces: `middleware(request: NextRequest): Promise<NextResponse>` in `frontend/middleware.ts` — on any request with no `session_token` cookie, calls 3A's `POST /api/v1/auth/guest`, sets the returned token as the session cookie (same options `lib/session.ts`'s `setSessionToken` already uses), and lets the request through either way (with or without a cookie, if the backend call fails).
- Consumes: `backendUrl(path: string): string` from `lib/backend.ts` (unchanged, already exported); 3A's `POST /api/v1/auth/guest` (returns `{access_token, token_type}`, same shape as `/auth/login`).

- [ ] **Step 1: Write the failing middleware tests**

Create `frontend/middleware.test.ts`:

```typescript
/**
 * @jest-environment node
 */
import { NextRequest } from "next/server";
import { middleware } from "./middleware";

describe("middleware guest-session bootstrap", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("mints a guest token and sets the session cookie when none exists", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ access_token: "guest-token-123", token_type: "bearer" }),
    }) as unknown as typeof fetch;

    const request = new NextRequest("http://localhost:3000/repos");
    const response = await middleware(request);

    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/auth/guest"), { method: "POST" });
    expect(response.cookies.get("session_token")?.value).toBe("guest-token-123");
  });

  it("does not mint a new guest when a session cookie already exists", async () => {
    global.fetch = jest.fn();

    const request = new NextRequest("http://localhost:3000/repos", {
      headers: new Headers({ cookie: "session_token=existing-token" }),
    });
    const response = await middleware(request);

    expect(fetch).not.toHaveBeenCalled();
    expect(response.cookies.get("session_token")).toBeUndefined();
  });

  it("lets the request through without a cookie when the backend is unreachable", async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error("network error"));

    const request = new NextRequest("http://localhost:3000/repos");
    const response = await middleware(request);

    expect(response.cookies.get("session_token")).toBeUndefined();
    expect(response.status).toBeLessThan(500);
  });

  it("does not mint a guest for a failed backend response", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 500 }) as unknown as typeof fetch;

    const request = new NextRequest("http://localhost:3000/repos");
    const response = await middleware(request);

    expect(response.cookies.get("session_token")).toBeUndefined();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npx jest middleware.test.ts` (from `frontend/`)
Expected: FAIL — `middleware.ts` doesn't export a named `middleware` function callable this way yet with this behavior (the current file only redirects, never fetches or sets cookies).

- [ ] **Step 3: Rewrite `middleware.ts`**

Replace the entire contents of `frontend/middleware.ts`:

```typescript
import { NextRequest, NextResponse } from "next/server";
import { backendUrl } from "@/lib/backend";

const SESSION_COOKIE = "session_token";

// The sole place a visitor's session is created. Every prior version of
// this middleware protected /repos/* by redirecting unauthenticated
// visitors to /login; there is no login anymore -- instead, the first
// request from a browser with no session cookie silently mints one via
// the backend's guest endpoint (sub-project 3A) and sets it here, before
// any page renders. Every existing proxy route and apiFetch's
// redirect-on-401 logic (lib/api-client.ts) keeps working completely
// unchanged; they simply always find a valid token now.
//
// lib/session.ts's setSessionToken() can't be reused directly here --
// it's built on next/headers' cookies(), which only works inside Server
// Components and Route Handlers, not Edge Middleware. The cookie options
// below are intentionally identical to that function's.
export async function middleware(request: NextRequest): Promise<NextResponse> {
  const existing = request.cookies.get(SESSION_COOKIE)?.value;
  const response = NextResponse.next();
  if (existing) {
    return response;
  }

  try {
    const guestResponse = await fetch(backendUrl("/api/v1/auth/guest"), { method: "POST" });
    if (guestResponse.ok) {
      const body = (await guestResponse.json()) as { access_token: string };
      response.cookies.set(SESSION_COOKIE, body.access_token, {
        httpOnly: true,
        secure: process.env.NODE_ENV === "production",
        sameSite: "lax",
        path: "/",
        maxAge: 60 * 60,
      });
    }
  } catch {
    // Backend unreachable -- let the request through without a cookie.
    // Every downstream proxy route already 401s cleanly on a missing
    // token, and apiFetch's existing redirect-on-401 handles the client
    // side; this middleware never blocks navigation on backend health.
  }
  return response;
}

export const config = {
  // Every request except Next's own static asset paths -- pages and API
  // proxy routes alike need a session cookie to exist before they run.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx jest middleware.test.ts`
Expected: all 4 tests PASS. If `NextRequest`/`NextResponse` behave differently under the `node` test environment than assumed above (e.g. `response.cookies.get(...)` shape), read the actual error and adjust the test's assertions to match real behavior — don't change `middleware.ts` to satisfy an assumption that turns out wrong, verify which side is actually wrong first.

- [ ] **Step 5: Delete the login/register pages, their tests, and their proxy routes**

```bash
git rm frontend/app/\(auth\)/login/page.tsx frontend/app/\(auth\)/login/page.test.tsx
git rm frontend/app/\(auth\)/register/page.tsx frontend/app/\(auth\)/register/page.test.tsx
git rm frontend/app/api/auth/login/route.ts frontend/app/api/auth/register/route.ts
```

(`frontend/app/api/auth/logout/route.ts` and `frontend/app/api/auth/me/route.ts` are NOT deleted — `logout` still meaningfully clears the guest cookie, `me` is low-cost to keep. Nothing in this plan's UI calls either right now; that's fine, they're small and independently useful.)

- [ ] **Step 6: Redirect the landing page straight into the workspace**

Replace the entire contents of `frontend/app/page.tsx`:

```typescript
import { redirect } from "next/navigation";

export default function HomePage() {
  redirect("/repos");
}
```

- [ ] **Step 7: Fix `app/repos/page.tsx`'s now-dead `/login` redirects**

`/login` no longer exists — redirecting there would 404. By the time this Server Component runs, the middleware has already guaranteed a session cookie exists on virtually every real request; the only way `fetchRepos` still sees a missing/invalid token is the rare case where the guest-mint itself failed (backend down). In `frontend/app/repos/page.tsx`, change the `fetchRepos` function (lines 9-19) from:

```typescript
async function fetchRepos(): Promise<Repo[]> {
  const token = getSessionToken();
  if (!token) redirect("/login");
  const res = await fetch(backendUrl("/api/v1/repos"), {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (res.status === 401) redirect("/login");
  if (!res.ok) return [];
  return res.json();
}
```

to:

```typescript
async function fetchRepos(): Promise<Repo[]> {
  const token = getSessionToken();
  // No /login to send anyone to anymore. A missing/invalid token here
  // means the middleware's guest-mint attempt itself failed (backend
  // unreachable) -- redirect to "/" so middleware gets another chance
  // on the next request, rather than rendering a broken authenticated
  // page or a 404 for a route that no longer exists.
  if (!token) redirect("/");
  const res = await fetch(backendUrl("/api/v1/repos"), {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (res.status === 401) redirect("/");
  if (!res.ok) return [];
  return res.json();
}
```

`redirect` is already imported in this file (used by the existing code).

- [ ] **Step 8: Run the full frontend suite, typecheck, and lint**

Run (from `frontend/`): `npx jest`, then `npx tsc --noEmit`, then `npx next lint`.
Expected: Jest suite passes (the deleted files' tests are gone, not failing; `middleware.test.ts` passes; every other existing test is unaffected). `tsc`/`lint` clean — in particular, confirm nothing else in the codebase still imports from the deleted `app/(auth)/*` or `app/api/auth/{login,register}` paths (grep for `"/login"` and `"/register"` across `frontend/` to be sure; the only pre-existing references were `repo-header.tsx` and `app/repos/page.tsx`, both already handled by this task and Task 2).

- [ ] **Step 9: Commit**

```bash
git add frontend/middleware.ts frontend/middleware.test.ts frontend/app/page.tsx frontend/app/repos/page.tsx
git commit -m "Replace login wall with transparent guest-session bootstrap in middleware"
```

---

### Task 2: Global AppHeader; fix repo-detail fetch; visual design system

**Files:**
- Create: `frontend/components/app-header.tsx`, `frontend/components/app-header.test.tsx`
- Create: `frontend/app/api/health/route.ts`
- Modify: `frontend/app/repos/layout.tsx` (render `AppHeader`)
- Modify: `frontend/components/workspace/repo-header.tsx` (remove sign-out button and its logic)
- Create: `frontend/app/api/repos/[repoId]/route.ts`, `frontend/app/api/repos/[repoId]/route.test.ts`
- Modify: `frontend/app/repos/[repoId]/page.tsx` (fetch the repo directly via 3A's new `GET /repos/{repo_id}` instead of list-and-filter)
- Modify: `frontend/app/globals.css` (retune color tokens to the zinc palette)
- Test: `frontend/components/workspace/repo-header.test.tsx` (new, replacing the deleted sign-out-only one), `frontend/app/repos/[repoId]/page.test.tsx` (update for the new fetch)

**Interfaces:**
- Produces: `AppHeader` component (no props — it's self-contained: renders the repo-quick-submit form, polls health, shows the GitHub link). New BFF proxy route `GET /api/health` (unauthenticated, proxies the backend's existing `GET /health`).
- Consumes: 3A's `GET /api/v1/repos/{repo_id}` (via a new proxy route this task also adds, `GET /api/repos/{repoId}` — wait, that proxy route already exists for other purposes, see Step 4 below for the exact reuse); `SubmitRepoForm`'s existing submission logic (unchanged, reused).

This task both adds the global header and fixes a real, load-bearing bug: `app/repos/[repoId]/page.tsx` currently fetches the workspace's repo metadata by calling `GET /api/repos` (the list) and filtering client-side for the matching id — under 3A's public-reads design, that list stays scoped to the caller, so a guest opening a repo link someone else submitted would incorrectly 404 even though every other endpoint on that repo is public. Fixing this is why this plan depends on 3A's Task 2 (`GET /repos/{repo_id}`) being complete first.

- [ ] **Step 1: Add the `GET /api/health` proxy route**

Create `frontend/app/api/health/route.ts`:

```typescript
import { NextResponse } from "next/server";
import { backendUrl } from "@/lib/backend";

export async function GET() {
  try {
    const res = await fetch(backendUrl("/health"), { cache: "no-store" });
    return NextResponse.json({ ok: res.ok }, { status: res.ok ? 200 : 502 });
  } catch {
    return NextResponse.json({ ok: false }, { status: 502 });
  }
}
```

(No auth needed — this reflects backend reachability, not anything user-specific. Note it deliberately wraps the backend's `{"status": "ok"}` shape into `{"ok": boolean}` rather than passing the raw body through, so `AppHeader` only needs a boolean, not backend-shape knowledge.)

- [ ] **Step 2: Write the failing `AppHeader` test**

Create `frontend/components/app-header.test.tsx`:

```typescript
import { render, screen, waitFor } from "@testing-library/react";
import { AppHeader } from "./app-header";

describe("AppHeader", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("shows a repo URL input for quick submission", () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) }) as unknown as typeof fetch;
    render(<AppHeader />);
    expect(screen.getByLabelText("GitHub repository URL")).toBeInTheDocument();
  });

  it("shows a healthy indicator when the health check succeeds", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) }) as unknown as typeof fetch;
    render(<AppHeader />);
    await waitFor(() => expect(screen.getByLabelText("Backend healthy")).toBeInTheDocument());
  });

  it("shows an unhealthy indicator when the health check fails", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, json: async () => ({ ok: false }) }) as unknown as typeof fetch;
    render(<AppHeader />);
    await waitFor(() => expect(screen.getByLabelText("Backend unreachable")).toBeInTheDocument());
  });

  it("hides the GitHub link when NEXT_PUBLIC_GITHUB_REPO_URL is unset", () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) }) as unknown as typeof fetch;
    render(<AppHeader />);
    expect(screen.queryByRole("link", { name: /github/i })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `npx jest app-header.test.tsx` (from `frontend/`)
Expected: FAIL — `./app-header` doesn't exist yet.

- [ ] **Step 4: Write `AppHeader`**

Create `frontend/components/app-header.tsx`:

```typescript
"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Github } from "lucide-react";
import { SubmitRepoForm } from "@/components/submit-repo-form";
import { cn } from "@/lib/utils";

const HEALTH_POLL_INTERVAL_MS = 15000;

export function AppHeader() {
  const [healthy, setHealthy] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function checkHealth() {
      try {
        const res = await fetch("/api/health", { cache: "no-store" });
        if (!cancelled) setHealthy(res.ok);
      } catch {
        if (!cancelled) setHealthy(false);
      }
    }

    checkHealth();
    const interval = setInterval(checkHealth, HEALTH_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const githubUrl = process.env.NEXT_PUBLIC_GITHUB_REPO_URL;

  return (
    <header className="sticky top-0 z-50 flex h-16 shrink-0 items-center justify-between gap-4 border-b border-zinc-800/80 bg-zinc-950/80 px-4 backdrop-blur-md">
      <span className="font-mono text-sm font-semibold tracking-tight text-zinc-100">Repo Analyzer</span>
      <div className="max-w-lg flex-1">
        <SubmitRepoForm compact />
      </div>
      <div className="flex items-center gap-3">
        {healthy === null ? null : healthy ? (
          <motion.span
            aria-label="Backend healthy"
            className="h-2 w-2 rounded-full bg-emerald-400"
            animate={{ opacity: [1, 0.4, 1] }}
            transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
          />
        ) : (
          <span aria-label="Backend unreachable" className="h-2 w-2 rounded-full bg-destructive" />
        )}
        {githubUrl && (
          <a
            href={githubUrl}
            target="_blank"
            rel="noreferrer"
            className={cn(
              "flex items-center gap-1.5 rounded-md border border-zinc-800/60 px-2.5 py-1.5 text-xs text-zinc-400 transition-colors hover:border-zinc-700/50 hover:text-zinc-100"
            )}
          >
            <Github className="h-3.5 w-3.5" /> Star
          </a>
        )}
      </div>
    </header>
  );
}
```

This introduces a `compact` prop on `SubmitRepoForm` it doesn't have yet — add it in the same step. In `frontend/components/submit-repo-form.tsx`: add `import { cn } from "@/lib/utils";` to the imports (this file doesn't import it today); change the function signature (line 11) from `export function SubmitRepoForm() {` to `export function SubmitRepoForm({ compact = false }: { compact?: boolean } = {}) {` (the `= {}` default keeps every existing no-props call site, e.g. `app/repos/page.tsx`'s `<SubmitRepoForm />`, compiling unchanged); change the `motion.form`'s `className` (line 50) from `"glass flex items-center gap-2 rounded-lg p-3"` to `cn("glass flex items-center gap-2 rounded-lg", compact ? "p-1.5" : "p-3")`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `npx jest app-header.test.tsx`
Expected: all 4 PASS.

- [ ] **Step 6: Render `AppHeader` from the shared layout**

In `frontend/app/repos/layout.tsx`, change:

```typescript
export default function ReposLayout({ children }: { children: React.ReactNode }) {
  return <div className="min-h-screen">{children}</div>;
}
```

to:

```typescript
import { AppHeader } from "@/components/app-header";

export default function ReposLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen">
      <AppHeader />
      {children}
    </div>
  );
}
```

(This layout wraps both `/repos` and, transitively, `/repos/[repoId]` — confirmed by reading `app/repos/[repoId]/layout.tsx`, which only adds its own `flex h-screen flex-col` wrapper inside this one, so `AppHeader` renders exactly once per page, on both routes.)

- [ ] **Step 7: Remove `RepoHeader`'s sign-out button**

In `frontend/components/workspace/repo-header.tsx`, remove: the `useState`/`useRouter` imports and the `loggingOut` state, the `handleLogout` function entirely, the `LogOut` icon import, and the `<Button ... onClick={handleLogout}>Sign out</Button>` JSX block. The file becomes:

```typescript
"use client";

import { motion } from "framer-motion";
import type { Job, Repo } from "@/lib/types";

// `job`/`polling` come from a single `useJobPolling` call owned by the
// parent page and shared with `FileTree`, rather than this component
// running its own independent poll of the same `GET /api/jobs/{id}` --
// see page.tsx.
export function RepoHeader({ repo, job, polling }: { repo: Repo; job: Job | null; polling: boolean }) {
  const status = job?.status ?? repo.status;

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-zinc-800/60 px-4">
      <div className="flex items-center gap-3">
        <span className="font-mono text-sm font-medium text-zinc-100">{repo.name}</span>
        {(polling || status === "running" || status === "pending") && (
          <motion.span
            className="h-2 w-2 rounded-full bg-yellow-400"
            animate={{ opacity: [1, 0.4, 1] }}
            transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
          />
        )}
        {status === "ready" || status === "completed" ? (
          <span className="h-2 w-2 rounded-full bg-emerald-400" />
        ) : null}
        {status === "failed" && <span className="h-2 w-2 rounded-full bg-destructive" />}
      </div>
      <div className="flex items-center gap-3">
        {job && job.status !== "completed" && job.status !== "failed" && (
          <span className="text-xs text-zinc-400">Analyzing... {job.progress}%</span>
        )}
        {job?.status === "failed" && (
          <span className="text-xs text-destructive">{job.error_message ?? "Analysis failed"}</span>
        )}
      </div>
    </header>
  );
}
```

Write its replacement test, `frontend/components/workspace/repo-header.test.tsx` (Task 1 deleted the old sign-out-only version of this file):

```typescript
import { render, screen } from "@testing-library/react";
import { RepoHeader } from "./repo-header";
import type { Repo } from "@/lib/types";

const repo: Repo = { id: "r1", url: "https://github.com/octocat/Hello-World", name: "Hello-World", status: "ready", created_at: "" };

describe("RepoHeader", () => {
  it("renders the repo name and a ready status dot", () => {
    render(<RepoHeader repo={repo} job={null} polling={false} />);
    expect(screen.getByText("Hello-World")).toBeInTheDocument();
  });

  it("has no sign-out control", () => {
    render(<RepoHeader repo={repo} job={null} polling={false} />);
    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 8: Fix the repo-detail fetch in `app/repos/[repoId]/page.tsx`**

Change the `useEffect` block (lines 28-47) from fetching the list and filtering:

```typescript
  useEffect(() => {
    let cancelled = false;
    setError(null);

    apiFetch("/api/repos", { cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load repositories");
        return res.json() as Promise<Repo[]>;
      })
      .then((repos) => {
        if (!cancelled) setRepo(repos.find((r) => r.id === params.repoId) ?? null);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load this repository.");
      });

    return () => {
      cancelled = true;
    };
  }, [params.repoId]);
```

to fetching that one repo directly:

```typescript
  useEffect(() => {
    let cancelled = false;
    setError(null);

    apiFetch(`/api/repos/${params.repoId}`, { cache: "no-store" })
      .then((res) => {
        if (res.status === 404) {
          if (!cancelled) setRepo(null);
          return null;
        }
        if (!res.ok) throw new Error("Failed to load repository");
        return res.json() as Promise<Repo>;
      })
      .then((repo) => {
        if (!cancelled && repo) setRepo(repo);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load this repository.");
      });

    return () => {
      cancelled = true;
    };
  }, [params.repoId]);
```

This needs a new BFF proxy route, `frontend/app/api/repos/[repoId]/route.ts` (the existing `frontend/app/api/repos/route.ts` only handles the collection — `GET`/`POST` on `/api/repos`, not a single id). Create it, mirroring the existing single-resource proxy routes' pattern (e.g. `frontend/app/api/jobs/[jobId]/route.ts`):

```typescript
import { NextRequest, NextResponse } from "next/server";
import { backendUrl } from "@/lib/backend";
import { getSessionToken } from "@/lib/session";

export async function GET(request: NextRequest, { params }: { params: { repoId: string } }) {
  const token = getSessionToken();
  if (!token) return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });

  const res = await fetch(backendUrl(`/api/v1/repos/${encodeURIComponent(params.repoId)}`), {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  const body = await res.json();
  return NextResponse.json(body, { status: res.status });
}
```

(`encodeURIComponent` on the path param, matching the security-review-driven pattern already used by every other proxy route in this codebase since sub-project 2B's final review.)

Add its test, `frontend/app/api/repos/[repoId]/route.test.ts`, matching the exact pattern the sibling `frontend/app/api/repos/[repoId]/files/route.test.ts` already establishes (the `@jest-environment node` docblock and `jest.mock("next/headers", ...)` cookie store are both required — Route Handlers import `next/server`, which needs real `Request`/`Response` globals jsdom doesn't provide):

```typescript
/**
 * @jest-environment node
 */
const store = new Map<string, string>();

jest.mock("next/headers", () => ({
  cookies: () => ({
    get: (name: string) => (store.has(name) ? { value: store.get(name) } : undefined),
  }),
}));

import { GET } from "./route";

describe("GET /api/repos/[repoId]", () => {
  afterEach(() => {
    store.clear();
    jest.restoreAllMocks();
  });

  it("encodes a '..'-containing repoId so it can't escape the intended backend URL path", async () => {
    store.set("session_token", "test-token");
    let capturedUrl = "";
    global.fetch = jest.fn((url: RequestInfo | URL) => {
      capturedUrl = url.toString();
      return Promise.resolve({ status: 200, json: async () => ({}) } as Response);
    }) as unknown as typeof fetch;

    await GET(new Request("http://localhost/api/repos/x"), { params: { repoId: "../../etc/passwd" } });

    expect(capturedUrl).toBe("http://localhost:8000/api/v1/repos/..%2F..%2Fetc%2Fpasswd");
    expect(capturedUrl).not.toContain("/etc/passwd");
  });

  it("returns 401 when no session cookie is present", async () => {
    const res = await GET(new Request("http://localhost/api/repos/x"), { params: { repoId: "x" } });
    expect(res.status).toBe(401);
  });
});
```

`frontend/app/repos/[repoId]/page.test.tsx` has 3 existing tests. The first two (`"shows a distinct error message... when the repos fetch rejects outright"` and `"...when the repos endpoint returns a non-ok status"`) both use an unconditional `global.fetch` mock (rejects, or returns a non-ok status regardless of URL) — neither needs any change, they still exercise the same code paths under the new single-repo fetch. The third, `"renders the workspace shell when the repo is found"`, currently mocks the response body as `json: async () => [repo]` (an array, matching the old list-based fetch) — change it to `json: async () => repo` (the single object the new endpoint returns; the mock's `status: 200`/`ok: true` already satisfy the new code's checks unchanged).

Also add a test for the now-explicit 404 path (previously only reachable implicitly via "not present in the array," never directly tested):

```typescript
  it("calls notFound() when the repo endpoint returns 404", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: "Repo not found" }),
    }) as unknown as typeof fetch;

    render(<RepoWorkspacePage params={{ repoId: "some-repo-id" }} />);

    await waitFor(() => {
      expect(screen.queryByTestId("workspace-shell")).not.toBeInTheDocument();
    });
  });
```

(This asserts the workspace shell never renders rather than asserting `notFound()` was called and threw, since the file's own `jest.mock("next/navigation", ...)` at the top makes `notFound()` throw `NEXT_NOT_FOUND` synchronously inside the component — asserting the render outcome is simpler than catching that thrown error through React's render cycle, and is exactly what the file's other two tests already do for their own error states.)

- [ ] **Step 9: Retune the color tokens in `globals.css`**

In `frontend/app/globals.css`, replace the `:root` block's color values (lines 6-24) — keep every variable name and every non-color line (`--radius`) exactly as-is, only change these color values:

```css
    --background: 240 10% 3.9%;   /* zinc-950 */
    --foreground: 240 4.8% 95.9%; /* zinc-100 */
    --card: 240 5.9% 10%;         /* zinc-900 */
    --card-foreground: 240 4.8% 95.9%;
    --border: 240 3.7% 15.9%;     /* zinc-800 */
    --input: 240 3.7% 15.9%;
    --secondary: 240 3.7% 15.9%;
    --secondary-foreground: 240 4.8% 95.9%;
    --muted: 240 3.7% 15.9%;
    --muted-foreground: 240 5% 64.9%; /* zinc-400 */
    --accent: 240 3.7% 15.9%;
    --accent-foreground: 240 4.8% 95.9%;
```

(`--primary`/`--ring` (currently `217 91% 60%`, a blue accent) and `--destructive` are unchanged — nothing in the approved design asks for a different accent hue, and it already reads cleanly against the darker background.)

Add a new utility to the existing `@layer utilities` block, alongside `.glass`/`.scrollbar-thin` — the "subtle neon rings and smooth shadows on active elements" requirement:

```css
  .elevated-ring {
    @apply ring-1 ring-zinc-700/50 shadow-sm;
  }
```

- [ ] **Step 10: Run the full frontend suite, typecheck, and lint**

Run: `npx jest`, then `npx tsc --noEmit`, then `npx next lint` (all from `frontend/`).
Expected: all pass. Visually spot-check by running `npm run dev` and loading `/repos` — confirm the header appears, the background reads as near-black zinc rather than the previous slightly-different dark tone, and no component looks obviously broken (this is a token-value change, not a class-name change, so most components should look identical modulo the exact shade).

- [ ] **Step 11: Commit**

```bash
git add frontend/components/app-header.tsx frontend/components/app-header.test.tsx frontend/app/api/health/route.ts frontend/app/api/repos/\[repoId\]/route.ts frontend/app/api/repos/\[repoId\]/route.test.ts frontend/app/repos/layout.tsx frontend/components/workspace/repo-header.tsx frontend/components/workspace/repo-header.test.tsx frontend/app/repos/\[repoId\]/page.tsx frontend/app/repos/\[repoId\]/page.test.tsx frontend/components/submit-repo-form.tsx frontend/app/globals.css
git commit -m "Add global AppHeader, fix repo-detail fetch to be public-read-safe, retune color tokens to zinc"
```

---

### Task 3: File explorer polish

**Files:**
- Modify: `frontend/components/workspace/file-tree-node.tsx`
- Test: `frontend/components/workspace/file-tree-node.test.tsx`

**Interfaces:**
- Consumes: `lib/highlight.ts`'s `EXTENSION_TO_LANG` map shape (not the map itself — this task adds a sibling map for icons, following the same "extension string → value" pattern already established there).

- [ ] **Step 1: Write the failing tests**

Add to `frontend/components/workspace/file-tree-node.test.tsx` (read the existing file first for its current structure/imports and match its patterns):

```typescript
it("shows a JSON-specific icon for a .json file", () => {
  const entry = { name: "package.json", path: "package.json", type: "file" as const, children: null };
  render(<FileTreeNode entry={entry} depth={0} selectedPath={null} onSelectFile={jest.fn()} />);
  expect(screen.getByTestId("file-icon-json")).toBeInTheDocument();
});

it("falls back to a generic file icon for an unrecognized extension", () => {
  const entry = { name: "data.xyz", path: "data.xyz", type: "file" as const, children: null };
  render(<FileTreeNode entry={entry} depth={0} selectedPath={null} onSelectFile={jest.fn()} />);
  expect(screen.getByTestId("file-icon-default")).toBeInTheDocument();
});

it("adds an accent border to the active file", () => {
  const entry = { name: "main.py", path: "src/main.py", type: "file" as const, children: null };
  render(<FileTreeNode entry={entry} depth={0} selectedPath="src/main.py" onSelectFile={jest.fn()} />);
  expect(screen.getByRole("button")).toHaveClass("border-l-2");
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npx jest file-tree-node.test.tsx` (from `frontend/`)
Expected: the first two FAIL (no `data-testid` exists yet on the icon), the third FAILS (`border-l-2` isn't applied yet).

- [ ] **Step 3: Add the extension-to-icon map and active-file border**

In `frontend/components/workspace/file-tree-node.tsx`, change the Lucide import (line 5) from `import { ChevronRight, File, Folder } from "lucide-react";` to:

```typescript
import { ChevronRight, File, FileCode2, FileJson, FileText, Folder } from "lucide-react";
```

Add this map above the `FileTreeNode` function (after the imports):

```typescript
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
```

In the `if (entry.type === "file")` branch, replace:

```typescript
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
```

with:

```typescript
      {(() => {
        const [Icon, iconKey] = iconForFile(entry.name);
        return (
          <button
            type="button"
            onClick={() => onSelectFile(entry.path)}
            style={{ paddingLeft: `${depth * 14 + 8}px` }}
            className={cn(
              "flex w-full items-center gap-1.5 rounded-sm border-l-2 border-transparent py-1 text-left text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground",
              selectedPath === entry.path && "border-primary bg-accent text-foreground"
            )}
          >
            <Icon data-testid={`file-icon-${iconKey}`} className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate font-mono text-xs">{entry.name}</span>
          </button>
        );
      })()}
```

(`border-l-2 border-transparent` on every row, not just the active one, so the active row's `border-primary` doesn't shift layout by 2px when it toggles — a transparent border of the same width reserves the space always.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx jest file-tree-node.test.tsx`
Expected: all PASS, including every pre-existing test in the file (accordion expand/collapse, folder rendering — untouched by this change).

- [ ] **Step 5: Run the full frontend suite, typecheck, and lint**

Run: `npx jest`, `npx tsc --noEmit`, `npx next lint` (from `frontend/`).
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/workspace/file-tree-node.tsx frontend/components/workspace/file-tree-node.test.tsx
git commit -m "Add per-extension file icons and active-file accent border to the file tree"
```

---

### Task 4: Code viewer polish

**Files:**
- Modify: `frontend/lib/highlight.ts` (Tokyo Night theme)
- Modify: `frontend/components/workspace/code-viewer.tsx` (sticky path header, copy button)
- Test: `frontend/lib/highlight.test.ts`, `frontend/components/workspace/code-viewer.test.tsx` (new)

**Interfaces:**
- Consumes: nothing new. Reuses the exact copy-button pattern already proven in `components/workspace/chat-message.tsx`'s `CodeBlock` (Copy/Check icon swap, 1.5s reset via `setTimeout`).

- [ ] **Step 1: Switch the Shiki theme**

In `frontend/lib/highlight.ts`, change line 26 from `createHighlighter({ themes: ["github-dark"], langs: SUPPORTED_LANGS })` to `createHighlighter({ themes: ["tokyo-night"], langs: SUPPORTED_LANGS })`, and line 41 from `theme: "github-dark"` to `theme: "tokyo-night"` (`tokyo-night` is a Shiki-bundled theme name — no new dependency).

Run: `npx jest lib/highlight.test.ts` (from `frontend/`). The existing tests assert only structural markers (`"<pre"`, the literal source text appearing in the output) — none hardcode a color value tied to `github-dark`, so this test file needs no changes and should pass unmodified against the new theme.

- [ ] **Step 2: Write the failing `CodeViewer` tests**

Create `frontend/components/workspace/code-viewer.test.tsx` (there is no existing test file for this component — check first in case one was added since this plan was written):

```typescript
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CodeViewer } from "./code-viewer";

describe("CodeViewer", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("shows a sticky path header with the current file's path", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ path: "src/main.py", content: "def main(): pass" }),
    }) as unknown as typeof fetch;

    render(<CodeViewer repoId="r1" path="src/main.py" />);

    await waitFor(() => expect(screen.getByText("src/main.py")).toBeInTheDocument());
  });

  it("copies the file's content and shows a checkmark", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ path: "src/main.py", content: "def main(): pass" }),
    }) as unknown as typeof fetch;
    Object.assign(navigator, { clipboard: { writeText: jest.fn().mockResolvedValue(undefined) } });

    render(<CodeViewer repoId="r1" path="src/main.py" />);
    const copyButton = await screen.findByLabelText("Copy file contents");

    await userEvent.click(copyButton);

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("def main(): pass");
    expect(await screen.findByLabelText("Copied")).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `npx jest code-viewer.test.tsx` (from `frontend/`)
Expected: FAIL — no path header text rendered, no "Copy file contents" labeled control exists yet.

- [ ] **Step 4: Add the sticky path header and copy button**

In `frontend/components/workspace/code-viewer.tsx`, the component needs the raw file content retained (for copying) alongside the already-highlighted HTML — currently `data.content` is piped straight into `highlightCode` and discarded. Change the state and fetch effect (lines 11-41):

```typescript
export function CodeViewer({ repoId, path }: { repoId: string; path: string | null }) {
  const [html, setHtml] = useState<string | null>(null);
  const [rawContent, setRawContent] = useState<string>("");
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!path) {
      setHtml(null);
      setError(null);
      return;
    }

    let cancelled = false;
    setHtml(null);
    setError(null);
    setCopied(false);

    apiFetch(`/api/repos/${repoId}/files/content?path=${encodeURIComponent(path)}`, { cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load file content");
        return res.json() as Promise<FileContentResponse>;
      })
      .then((data) => {
        if (!cancelled) setRawContent(data.content);
        return highlightCode(data.content, path);
      })
      .then((highlighted) => {
        if (!cancelled) setHtml(highlighted);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load this file's content.");
      });

    return () => {
      cancelled = true;
    };
  }, [repoId, path]);

  async function handleCopy() {
    await navigator.clipboard.writeText(rawContent);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }
```

Then, in the final successful-render branch (currently just the `motion.div` with `dangerouslySetInnerHTML`), wrap it with the sticky header:

```typescript
  return (
    <div className="flex h-full flex-col">
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-zinc-800/60 bg-card/60 px-4 py-2 backdrop-blur-sm">
        <span className="truncate font-mono text-xs text-zinc-400">{path}</span>
        <button
          type="button"
          onClick={handleCopy}
          aria-label={copied ? "Copied" : "Copy file contents"}
          className="rounded-md border border-zinc-800/60 p-1 text-zinc-400 transition-colors hover:text-zinc-100"
        >
          {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
      </div>
      <motion.div
        key={path}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.15 }}
        className="shiki-line-numbers flex-1 overflow-auto p-4 font-mono text-sm leading-relaxed [&_pre]:!bg-transparent [&_pre]:whitespace-pre"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
```

Add `import { Check, Copy } from "lucide-react";` to this file's imports. This header only makes sense once `html` is loaded — since the component's other branches (`!path`, `error`, `html === null` loading skeleton) `return` early before reaching this block, the sticky header naturally only appears once a file is actually showing; no extra conditional needed.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npx jest code-viewer.test.tsx`
Expected: both PASS.

- [ ] **Step 6: Run the full frontend suite, typecheck, and lint**

Run: `npx jest`, `npx tsc --noEmit`, `npx next lint` (from `frontend/`).
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/lib/highlight.ts frontend/lib/highlight.test.ts frontend/components/workspace/code-viewer.tsx frontend/components/workspace/code-viewer.test.tsx
git commit -m "Switch code viewer to Tokyo Night theme; add sticky path header and copy button"
```

---

### Task 5: Chat panel polish

**Files:**
- Modify: `frontend/components/workspace/chat-panel.tsx` (quick-prompt pills, streaming glow cursor)
- Test: `frontend/components/workspace/chat-panel.test.tsx`

**Interfaces:**
- Consumes: `handleSend(content: string)` (already defined in `ChatPanel`, unchanged signature) — quick-prompt pills call it directly, no new submission path.

- [ ] **Step 1: Write the failing tests**

Add a new `describe` block to `frontend/components/workspace/chat-panel.test.tsx`, following the exact `global.fetch` URL/method-keyed mocking pattern the file's existing `describe` blocks already use (each mocks `GET /api/repos/repo-1/conversations`, `GET /api/conversations/c1/messages`, and `POST /api/conversations/c1/messages` by exact URL string):

```typescript
describe("ChatPanel quick prompts and streaming cursor", () => {
  const conversation = { id: "c1", repo_id: "repo-1", title: "New conversation", created_at: "" };

  it("shows quick-prompt pills when the active conversation has no messages yet", async () => {
    global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      const method = init?.method ?? "GET";

      if (url === "/api/repos/repo-1/conversations" && method === "GET") {
        return Promise.resolve({ ok: true, json: async () => [conversation] } as Response);
      }
      if (url === "/api/conversations/c1/messages" && method === "GET") {
        return Promise.resolve({ ok: true, json: async () => [] } as Response);
      }
      throw new Error(`Unexpected fetch: ${method} ${url}`);
    }) as unknown as typeof fetch;

    render(<ChatPanel repoId="repo-1" />);

    expect(await screen.findByRole("button", { name: "Explain repo architecture" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Find security vulnerabilities" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "List API routes" })).toBeInTheDocument();
  });

  it("clicking a quick-prompt pill sends it immediately via the existing send path", async () => {
    global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      const method = init?.method ?? "GET";

      if (url === "/api/repos/repo-1/conversations" && method === "GET") {
        return Promise.resolve({ ok: true, json: async () => [conversation] } as Response);
      }
      if (url === "/api/conversations/c1/messages" && method === "GET") {
        return Promise.resolve({ ok: true, json: async () => [] } as Response);
      }
      if (url === "/api/conversations/c1/messages" && method === "POST") {
        expect(JSON.parse(init?.body as string)).toEqual({ content: "List API routes" });
        return Promise.resolve({
          ok: true,
          body: makeStreamingBody([
            sseFrame("token", { text: "Here are the routes." }),
            sseFrame("done", { message_id: "m2" }),
          ]),
        } as unknown as Response);
      }
      throw new Error(`Unexpected fetch: ${method} ${url}`);
    }) as unknown as typeof fetch;

    render(<ChatPanel repoId="repo-1" />);
    const pill = await screen.findByRole("button", { name: "List API routes" });

    await userEvent.click(pill);

    expect(await screen.findByText("Here are the routes.")).toBeInTheDocument();
  });

  it("shows a streaming cursor while a response is still arriving", async () => {
    // A reader whose stream never signals `done` after its first token,
    // simulating a response still in flight -- so isStreaming stays true
    // for the duration of this test instead of settling immediately.
    function makeHangingStreamingBody(frames: string[]) {
      const encoder = new TextEncoder();
      let i = 0;
      return {
        getReader() {
          return {
            async read() {
              if (i < frames.length) {
                const chunk = encoder.encode(frames[i]);
                i += 1;
                return { done: false, value: chunk };
              }
              return new Promise(() => {}); // never resolves -- stream stays "open"
            },
          };
        },
      };
    }

    global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      const method = init?.method ?? "GET";

      if (url === "/api/repos/repo-1/conversations" && method === "GET") {
        return Promise.resolve({ ok: true, json: async () => [conversation] } as Response);
      }
      if (url === "/api/conversations/c1/messages" && method === "GET") {
        return Promise.resolve({ ok: true, json: async () => [] } as Response);
      }
      if (url === "/api/conversations/c1/messages" && method === "POST") {
        return Promise.resolve({
          ok: true,
          body: makeHangingStreamingBody([sseFrame("token", { text: "Still working..." })]),
        } as unknown as Response);
      }
      throw new Error(`Unexpected fetch: ${method} ${url}`);
    }) as unknown as typeof fetch;

    render(<ChatPanel repoId="repo-1" />);
    const textbox = screen.getByPlaceholderText("Ask about this repo...");
    await waitFor(() => expect(textbox).not.toBeDisabled());

    await userEvent.type(textbox, "hi");
    await userEvent.click(screen.getByLabelText("Send message"));

    expect(await screen.findByTestId("streaming-cursor")).toBeInTheDocument();
  });
});
```

`sseFrame` and `makeStreamingBody` are already defined at the top of this file (used by the existing `describe` blocks) — reused here verbatim, not redefined.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npx jest chat-panel.test.tsx` (from `frontend/`)
Expected: all three new tests FAIL (no pills exist yet, no `streaming-cursor` test id exists yet).

- [ ] **Step 3: Add quick-prompt pills**

In `frontend/components/workspace/chat-panel.tsx`, add a constant above the `ChatPanel` function:

```typescript
const QUICK_PROMPTS = ["Explain repo architecture", "Find security vulnerabilities", "List API routes"];
```

In the JSX, the empty-state message currently reads:

```typescript
            {messages.length === 0 && !isStreaming && (
              <p className="p-4 text-center text-sm text-muted-foreground">
                {activeId ? "No messages yet. Ask something below." : "Start a conversation to chat about this repo."}
              </p>
            )}
```

Change it to also render the pills when there's an active conversation with no messages yet:

```typescript
            {messages.length === 0 && !isStreaming && (
              <div className="space-y-3 p-4 text-center">
                <p className="text-sm text-muted-foreground">
                  {activeId ? "No messages yet. Ask something below." : "Start a conversation to chat about this repo."}
                </p>
                {activeId && (
                  <div className="flex flex-wrap justify-center gap-2">
                    {QUICK_PROMPTS.map((prompt) => (
                      <button
                        key={prompt}
                        type="button"
                        onClick={() => handleSend(prompt)}
                        className="rounded-full border border-zinc-800/60 px-3 py-1.5 text-xs text-zinc-400 transition-colors hover:border-zinc-700/50 hover:text-zinc-100"
                      >
                        {prompt}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
```

`handleSend` is already defined in this component (used by `ChatInput`'s `onSend`) — the pills call it directly, same function, no duplication.

- [ ] **Step 4: Add the streaming glow cursor**

`tailwind.config.ts` already defines `animation: { "pulse-subtle": "pulse-subtle 1.8s ease-in-out infinite" }` (used elsewhere in the codebase, e.g. the repo-header status dot's spirit) — reuse it rather than defining a new keyframe. In the `isStreaming` block, currently:

```typescript
                {streamingText && <ChatMessage role="assistant" content={streamingText} />}
```

Change to:

```typescript
                {streamingText && (
                  <div className="flex items-end gap-1">
                    <ChatMessage role="assistant" content={streamingText} />
                    <span
                      data-testid="streaming-cursor"
                      className="mb-2 h-3 w-1.5 shrink-0 animate-pulse-subtle rounded-sm bg-primary"
                    />
                  </div>
                )}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npx jest chat-panel.test.tsx`
Expected: all PASS, including every pre-existing test in the file (auto-scroll, retry, conversation switching — none of this task's changes touch that logic).

- [ ] **Step 6: Run the full frontend suite, typecheck, and lint**

Run: `npx jest`, `npx tsc --noEmit`, `npx next lint` (from `frontend/`).
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/components/workspace/chat-panel.tsx frontend/components/workspace/chat-panel.test.tsx
git commit -m "Add quick-prompt suggestion pills and a streaming glow cursor to the chat panel"
```

---

### Task 6: Playwright suite update; final build validation; README

**Files:**
- Modify: `frontend/tests/e2e/full-flow.spec.ts` (drop the register/login steps)
- Modify: root `README.md`

**Interfaces:**
- Consumes: nothing new — this task only removes now-invalid steps from an existing spec and documents the finished behavior.

- [ ] **Step 1: Remove the register/login steps from the Playwright spec**

Read `frontend/tests/e2e/full-flow.spec.ts` as it currently exists. It begins with steps that register a new account and log in before submitting a repo — both are gone now (Task 1 deleted those pages entirely). Remove those steps; the spec should now start by navigating directly to `/` (which redirects to `/repos` per Task 1's landing-page change) and go straight to submitting a repo. Every assertion from that point on (file tree, code viewer, chat, reload-persistence) is unaffected and stays as-is — this is a deletion of now-invalid setup steps, not a rewrite of the spec's actual assertions.

This suite already has a known, pre-existing gap from sub-project 2B's merge (its local fixture-git server can't satisfy the backend's shallow clone, so it fails on a git transport error). That gap is unrelated to this change and is not this task's to fix — don't attempt to make the suite pass end-to-end as part of this step; just remove the now-dead auth steps so the spec's *content* correctly reflects the app's current flow, whenever someone does fix the fixture-server gap.

- [ ] **Step 2: Update the README**

Find the section documenting the app's user flow (likely written during sub-project 2B, describing registration/login as the entry point). Update it to describe the actual current flow: visiting the app lands directly in the repo workspace, no account needed — a guest session is created transparently. Mention `NEXT_PUBLIC_GITHUB_REPO_URL` as an optional env var for the header's Star/Fork link, unset by default (link hidden).

- [ ] **Step 3: Final full-plan verification**

From `frontend/`: `npx jest` (all suites), `npx tsc --noEmit`, `npx next lint`, then `npm run build` — this must complete with zero TypeScript and zero ESLint errors, the explicit acceptance criterion from the original request. This is the one point in this plan where every prior task's changes are verified together, not just individually.

Then a manual walkthrough on `localhost:3000` (via `npm run dev`, with the backend running per 3A's own manual-verification setup, `LLM_PROVIDER=fake` for a deterministic chat reply): confirm the landing page goes straight to the workspace with no login prompt, the header's health dot turns green, submitting a repo works, the file tree/code viewer/chat panel all render with the new zinc palette and Tokyo Night code theme, and a fresh incognito/private window (no cookies) gets its own working guest session with no visible bootstrap delay or error.

- [ ] **Step 4: Commit**

```bash
git add frontend/tests/e2e/full-flow.spec.ts README.md
git commit -m "Update e2e suite for guestless flow; document guest access and GitHub link config in README"
```
