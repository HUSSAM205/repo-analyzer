# Repo Analyzer — Sub-Project 3B: Public SaaS Frontend

Status: Approved
Date: 2026-08-17

## Purpose

Remove the last-mile login wall from the actual product experience (the
backend groundwork is sub-project 3A) and reskin the entire app to a
Linear/Raycast/Cursor-style dark SaaS aesthetic. A visitor's first click
should land them in the working repository workspace, paste-ready — no
account, no form, no wait.

This sub-project depends on 3A being complete: the guest-bootstrap flow
below calls `POST /api/v1/auth/guest`, and the header's GitHub-link and
health-dot behavior assume 3A's public-read endpoints.

## Non-goals (this sub-project)

- No backend changes — everything here consumes 3A's API as-is.
- No mobile/phone layout, same standing constraint as sub-project 2B —
  desktop/laptop responsive only, collapsible sidebar for narrower
  windows.
- No account system, no "claim this guest session" upgrade path, no
  user settings/profile UI — there is no user concept exposed in the UI
  at all now. (3A leaves the backend register/login endpoints intact for
  a possible future account feature; this sub-project simply never
  calls them.)
- No new Playwright fixtures beyond adjusting the existing suite for the
  removed auth steps (see Testing) — no new e2e scenarios are added for
  this sub-project's own sake.
- The GitHub Star/Fork link target is a placeholder
  (`NEXT_PUBLIC_GITHUB_REPO_URL`, hidden if unset) until a real public
  repo URL exists, per the approved design.

## Architecture

### Guest-session bootstrap

`middleware.ts` currently exists solely to redirect unauthenticated
visitors away from `/repos/*` to `/login`. It is repurposed: on every
request (matcher widened from `/repos/:path*` to everything except
Next's static asset paths), if no `session_token` cookie is present, the
middleware calls 3A's `POST /api/v1/auth/guest` server-side, and sets the
returned token on the response via `NextResponse.next()` +
`response.cookies.set(...)` — identical cookie options
(`httpOnly`, `sameSite: "lax"`, `maxAge: 60*60`) `lib/session.ts`
already uses for a real login, so every existing proxy route and
`apiFetch`'s 401-redirect logic keeps working completely unchanged; they
simply always find a valid token now. This is the only place a
visitor's "session" is created — no form, no redirect, no visible
transition. `middleware.ts` no longer redirects anyone anywhere; the
login-wall logic is deleted outright, not disabled behind a flag.

If the guest-provisioning fetch itself fails (backend down), the
middleware lets the request through without a cookie — every downstream
proxy route already 401s cleanly on a missing/invalid token
(`apiFetch`'s existing redirect-on-401 behavior), so the failure mode is
"the app doesn't work until the backend is back," not a crash or an
infinite loop.

### Removed: login/register

`app/(auth)/login/`, `app/(auth)/register/`, and their tests are deleted
outright. The BFF proxy routes `app/api/auth/login/route.ts` and
`app/api/auth/register/route.ts` are also deleted (nothing in the UI
calls them anymore, and 3A's guest endpoint is what the middleware calls
instead) — `app/api/auth/logout/route.ts` and `.../me/route.ts` stay,
since `logout` is still meaningful (clears the guest cookie, middleware
mints a fresh guest on the next request) and `me` is low-cost to keep
and may be useful for debugging.

### Landing page

`app/page.tsx`'s marketing splash is replaced with a server-side
`redirect("/repos")` (`next/navigation`). `/repos` — already the
dashboard listing a visitor's own analyzed repos plus the submit-a-URL
form — becomes the de facto landing experience. No new route structure;
this is a one-file change.

### Global sticky header

A new `AppHeader` component carries everything that isn't specific to a
particular repo, and renders on **both** `/repos` (the list/dashboard)
and `/repos/[repoId]` (the workspace) — it can't be `RepoHeader` itself,
since that component's props require an already-analyzed `repo` object
that doesn't exist yet on the list page:

- `sticky top-0 z-50 backdrop-blur-md bg-zinc-950/80 border-b border-zinc-800/80`.
- A compact repo-URL input (reusing `SubmitRepoForm`'s existing submit
  logic in a condensed inline layout) so a visitor can analyze a new
  repo or jump to a different one without leaving the workspace.
- A pulsing status dot reflecting real backend health: a new
  `GET /api/health` BFF proxy route (unauthenticated, calls the
  backend's existing `GET /health`) polled every ~15s; green+pulsing
  when reachable, a static red/gray dot when not. This reflects backend
  reachability, not per-message LLM streaming state — an active chat
  stream already has its own glowing cursor (see below) for that.
- The GitHub Star/Fork link (placeholder target, see Non-goals),
  right-aligned where a login/profile control used to be.

`AppHeader` is rendered once, above everything else, from a shared
layout (`app/repos/layout.tsx`, which already wraps both the list and
workspace routes). `RepoHeader` keeps its current, smaller job — the
per-repo name and analyzing-status dot — rendered just below `AppHeader`
only inside the workspace route; its existing "Sign out" button is
deleted (there's no login concept left to sign out of). The two
components don't overlap in content, so there's no duplicated chrome.

### Visual design system

Inter (sans) and JetBrains Mono (mono) are already wired via
`next/font/google` in `layout.tsx` — no font change needed, this
requirement is already met.

The color system stays on its current architecture (semantic CSS custom
properties consumed via Tailwind's `hsl(var(--x))`, not a wholesale
switch to literal `zinc-*` classes scattered through every component) —
retuning the *values* of the existing tokens to the requested zinc scale
gets pixel-identical results with a far smaller, far more reviewable
diff than rewriting every `bg-*`/`text-*`/`border-*` class across the
whole component tree. `app/globals.css`'s `:root` block changes to:

```
--background: 240 10% 3.9%;   /* zinc-950 */
--card:       240 5.9% 10%;   /* zinc-900 */
--border:     240 3.7% 15.9%; /* zinc-800 */
--input:      240 3.7% 15.9%; /* zinc-800 */
--secondary:  240 3.7% 15.9%; /* zinc-800 */
--accent:     240 3.7% 15.9%; /* zinc-800 */
--muted:      240 3.7% 15.9%; /* zinc-800 */
--foreground:        240 4.8% 95.9%; /* zinc-100 */
--muted-foreground:  240 5% 64.9%;   /* zinc-400 */
```
`--primary`/`--ring` (currently a blue accent, `217 91% 60%`) are
unchanged — nothing in the approved request asks for a different accent
hue, and it already reads as a clean interactive/focus color against the
new darker background. `--card` gets used at `/60` opacity
(`bg-card/60`) specifically on elevated surfaces (panels, popovers) per
the "Elevated cards: bg-zinc-900/60" requirement — a Tailwind opacity
suffix on the existing token, not a new one.

New utility in `globals.css`, applied to elevated/active surfaces (the
active file-tree row, a focused input, hovered cards) rather than
globally: `ring-1 ring-zinc-700/50 shadow-sm` — a literal utility
combination applied directly at the call sites named in the request
(not abstracted into `.glass`, which already exists for a different,
heavier blur treatment used by the chat input).

### File explorer (left pane)

`FileTreeNode` already has Lucide `File`/`Folder` icons, animated
chevron rotation, and smooth height-animated accordions (Framer Motion)
— the accordion/expand mechanics need no change. Two additions:
- Icon-per-extension: replace the single generic `File` icon with a
  small extension→icon map (Lucide already ships enough distinct icons
  for the common cases — e.g. `FileJson`, `FileCode`, `FileType` for
  `.ts`/`.tsx`, a generic `FileText` fallback) mirroring the existing
  `EXTENSION_TO_LANG` map's shape in `lib/highlight.ts`.
- Active-file accent border: the existing `selectedPath === entry.path`
  branch gains a left accent border (`border-l-2 border-primary`) in
  addition to its current background-highlight treatment.

### Code viewer (center pane)

- Shiki theme switches from `"github-dark"` to `"tokyo-night"` (a
  bundled Shiki theme, no new dependency) in both
  `createHighlighter({ themes: [...] })` and the `codeToHtml(...)` call
  in `lib/highlight.ts`.
- Sticky file-path header: a small bar above the highlighted content
  showing the current file's path, `sticky top-0` within the pane's
  scroll container, `bg-card/60` to match the elevated-surface treatment
  above.
- Copy-code button with checkmark feedback: `ChatMessage`'s
  `CodeBlock` already has exactly this pattern (`Copy`/`Check` icon
  swap, 1.5s reset) — add the same button, same behavior, to
  `CodeViewer` itself (it currently has none), reusing the pattern
  rather than inventing a second one.

### AI assistant (right pane)

- Chat bubbles, markdown rendering with syntax-highlighted code blocks,
  and copy buttons already exist (`ChatMessage`/`CodeBlock`) — visual
  tokens above (zinc palette, Tokyo Night-consistent code coloring)
  apply automatically through the retuned CSS variables and needs no
  new component logic.
- Streaming glow cursor: `ChatPanel`'s in-flight assistant message
  (already tracked as local streaming state from sub-project 2B Task 9)
  gets a small trailing pulsing caret (reuses the existing
  `animate-pulse-subtle` keyframe already defined in
  `tailwind.config.ts`) appended while tokens are still arriving,
  removed once the stream's `done` event lands.
- Quick-prompt suggestion pills: a new row of 3-4 preset prompts (e.g.
  "Explain repo architecture", "Find security vulnerabilities", "List
  API routes") shown above `ChatInput` only when a conversation has no
  messages yet. Clicking one prefills and immediately sends — reuses
  `ChatPanel`'s existing send path verbatim, no new submission logic.

## Data flow (guest-to-chat, illustrative)

1. Visitor's browser has no cookie. First request (even just loading
   `/`) hits `middleware.ts`, which mints a guest token via 3A's
   endpoint and sets it on the response.
2. `/` redirects to `/repos`; the header's quick-input and the page's
   `SubmitRepoForm` both post to the existing `POST /api/repos` proxy,
   which now (per 3A) either starts a fresh analysis or returns an
   already-`READY` repo's id instantly.
3. Visitor lands on `/repos/[repoId]`, browses files, opens a
   conversation, sends a message — every step identical to sub-project
   2B's existing flow, just with a guest token instead of a real login's
   token, and (per 3A) visible even if a different guest originally
   submitted this repo.

## Error handling

- Guest-mint failure in middleware degrades to "no cookie set, requests
  401, existing `apiFetch` redirect-on-401 fires" — already-handled
  behavior, no new error path introduced.
- Health-dot polling failure (network error, non-200) renders the
  static/red state — never throws, never blocks the rest of the header.
- Every other error-handling path (file load failure, chat send/stream
  failure and its retry button, repo submission failure) is unchanged
  from sub-project 2B.

## Testing

- Component tests updated for every touched component (`FileTreeNode`'s
  new icon map, `CodeViewer`'s new copy button and sticky header,
  `ChatPanel`'s quick-prompt pills, the header's health-dot polling and
  repo-quick-switch input) — new assertions alongside existing ones, not
  wholesale rewrites where behavior didn't change.
- `middleware.ts`'s guest-bootstrap logic gets its own test (mocks the
  guest endpoint, confirms the cookie gets set on a cookie-less request
  and is left alone on a request that already has one).
- Existing Playwright suite (`full-flow.spec.ts`) drops its
  register/login steps — the flow now starts directly at repo
  submission, since there's no account to create. The rest of the
  suite's assertions (file tree, code viewer, chat, reload-persistence)
  are otherwise unchanged. Note: this suite already carries a known,
  pre-existing gap from sub-project 2B's merge (its local fixture-git
  server can't satisfy the backend's shallow clone, so it fails on a git
  transport error independent of anything in this sub-project) — that
  gap is not this sub-project's to fix; don't mistake a still-red suite
  for a regression introduced here.
- Visual/build validation: `npm run build` (equivalently `next build`)
  must complete with zero TypeScript and zero ESLint errors before this
  sub-project is considered done — explicit acceptance criterion from
  the original request, verified as part of the normal per-task review
  gate (same `tsc --noEmit` / `next lint` checks already run for every
  prior frontend task) rather than a special one-off step.
- Manual verification: the full guest flow (fresh browser profile, no
  cookies) walked end-to-end on `localhost:3000` — landing → instant
  workspace access → analyze a repo → chat with the real Gemini
  provider (once 3A's key is confirmed working) — same live-walkthrough
  pattern used for every prior sub-project's final verification.

## Future sub-projects (not in scope here)

- An account/"claim this session" upgrade path, if guest-only ever
  proves insufficient.
- A public gallery/showcase view of previously analyzed repos (3A's
  data model — global dedup by URL — would support this cheaply if it's
  ever wanted; today's `GET /repos` stays personal per the approved
  design).
