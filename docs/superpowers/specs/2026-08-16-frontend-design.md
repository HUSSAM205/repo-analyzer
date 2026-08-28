# Repo Analyzer — Sub-Project 2B: Next.js Frontend & Full-Stack Packaging

Status: Approved (sub-project 2A merged; implementation begins now)
Date: 2026-08-16 (visual design / animation detail added 2026-08-16)

## Purpose

Build the IDE-style web UI on top of sub-project 2A's API: browse an
analyzed repo's file tree, view real syntax-highlighted source, and
chat with the multi-agent engine about the codebase — with real-time
streaming responses. Package the whole system (postgres, redis, api,
worker, frontend) to boot together via one `docker compose up`.

This sub-project cannot start until 2A is merged — every screen here
depends on an API surface 2A builds (file tree, file content,
conversations, streaming chat).

## Non-goals (this sub-project)

- No architecture diagrams (matches 2A's non-goal — no call-graph data
  exists to render)
- No multi-repo dashboard/workspace switcher polish beyond a simple
  repo picker — this phase is "open one analyzed repo and use it well,"
  not a full SaaS shell
- No offline/PWA support, no mobile-specific layout (desktop-first,
  IDE-style layouts don't meaningfully work on phone-sized screens)
- No collaborative/multi-user real-time features (e.g. shared cursors)

## Architecture

**Stack:** Next.js 14 (App Router), TypeScript, Tailwind CSS,
shadcn/ui components, Framer Motion for animation, dark mode by
default (no light-mode toggle in this phase — one deliberate,
well-executed theme beats a half-tested second one).

**Visual design:** Dark theme with 1px low-opacity borders throughout
for structure. Glassmorphism (backdrop-blur + translucent surface) is
reserved for elevated/floating elements only — the chat input bar,
dropdowns, modals — not applied to the whole UI, so it reads as a
deliberate accent rather than a gimmick. Typography: a clean geometric
sans for UI chrome (Geist or Inter), a proper monospace for the code
viewer and chat code blocks (JetBrains Mono). Framer Motion drives:
page/panel transitions, file-tree expand/collapse, panel
resize/collapse, skeleton loaders during data fetches, and pulsing
indicators (streaming cursor, "searching code..." state) — all kept
subtle (150-250ms, standard easing) rather than showy, consistent with
"developer tool," not "marketing site."

**Responsive:** panes resize and collapse gracefully across
desktop/laptop widths (a 1280px laptop through a 1920px+ external
monitor), with a collapsible-sidebar mode for narrower windows within
that range. Still desktop/laptop-only — no dedicated phone/mobile
layout (see Non-goals).

**Pages:**
- `/login`, `/register` — thin forms against the existing
  `/api/v1/auth/*` endpoints (sub-project 1), JWT stored client-side
  (httpOnly cookie via a Next.js route handler proxy, not raw
  localStorage, to reduce XSS exposure to the token).
- `/repos` — list the user's analyzed repos (existing
  `POST /repos/analyze` + a to-be-added `GET /repos` list endpoint —
  see Backend additions below) with status/progress, and a form to
  submit a new one.
- `/repos/[repoId]` — the 3-pane IDE workspace: file tree (left), code
  viewer (middle), chat (right).

**3-pane workspace components:**
- **File tree (left):** collapsible directory tree from
  `GET /repos/{repoId}/files`, click a file to load it into the
  viewer. Client-side tree state (expanded/collapsed) only — no
  backend round-trip per toggle.
- **Code viewer (middle):** fetches `GET /repos/{repoId}/files/content`
  for the selected file, renders with syntax highlighting (Shiki —
  same highlighter VS Code uses, good language coverage matching the
  backend's supported languages plus graceful fallback for others).
  Read-only; no editing in this phase.
- **Chat panel (right):** conversation list/picker backed by
  `GET/POST /repos/{repoId}/conversations`, message history from
  `GET /conversations/{id}/messages`, new messages sent via
  `POST /conversations/{id}/messages` consumed as an SSE stream
  (`EventSource` or a fetch-based SSE reader for auth-header support,
  since `EventSource` can't send custom headers — needed for the JWT).
  Renders assistant messages as markdown with syntax-highlighted code
  blocks (react-markdown + the same Shiki highlighter as the code
  viewer, for visual consistency), streaming tokens appended live as
  they arrive rather than waiting for the full message. Every rendered
  code block has a copy-to-clipboard button. The message list
  auto-scrolls to bottom as tokens stream in, except when the user has
  manually scrolled up to read earlier messages — in that case a
  "jump to bottom" affordance appears instead of fighting their scroll
  position.

**Backend additions needed for this sub-project** (small, added here
since they're pure frontend-support endpoints with no new domain
logic — not folded into 2A because 2A's scope is the agent engine and
file storage, not repo listing):
- `GET /api/v1/repos` — list the requesting user's repos with status,
  to populate `/repos`.

## Data flow

1. User logs in → JWT stored (httpOnly cookie via a Next.js route
   handler that proxies to the FastAPI auth endpoints).
2. `/repos` loads the user's repo list; submitting a new URL calls the
   existing `POST /repos/analyze` and polls `GET /jobs/{id}` (existing
   endpoints, unchanged) until the job completes, then the repo
   becomes clickable.
3. Opening `/repos/[repoId]` loads the file tree; clicking a file
   fetches and renders its content.
4. In the chat panel, sending a message opens an SSE connection to
   `POST /conversations/{id}/messages`; incoming `token` events append
   to the in-progress assistant message live; a `tool_call` event
   shows a brief "searching code..." indicator; `done` finalizes the
   message; `error` shows an inline error state with a retry action.

## Error handling

- API errors (401 expired token, 404 not-your-repo, 5xx) render as
  clear inline UI states, not blank screens or uncaught exceptions —
  a 401 redirects to `/login`.
- SSE connection drops (network blip, server restart mid-stream) are
  detected and surfaced as a retry-able error state in the chat panel,
  not a silently stuck "thinking..." spinner.
- File tree/viewer handle an empty repo (job completed but produced no
  files, or a file that failed to load) with an explicit empty/error
  state, not a blank pane.

## Testing

- Component-level tests for the file tree, code viewer, and chat
  message rendering (React Testing Library) — pure rendering logic,
  no network.
- Playwright end-to-end test covering the full flow against the real
  backend (docker-composed, with `FakeLLMClient` active since no real
  API key is assumed by default): register → login → submit a repo →
  wait for analysis to complete → open the repo → browse the file
  tree → view a file's content → send a chat message → see a streamed
  response appear → verify it's persisted (reload, history still
  there).
- No live GitHub or live LLM calls in the Playwright suite by default —
  it runs against the same local fixture-repo pattern sub-project 1's
  worker tests use, and the backend's `FakeLLMClient` for chat,
  keeping the suite fast and deterministic in CI.

## Containerization

- `frontend/Dockerfile` — multi-stage (deps → build → runtime),
  `next build` in the build stage, a minimal runtime image serving the
  production build (`next start` or the Next.js standalone output).
- `frontend` service added to the root `docker-compose.yml`, depending
  on `api` being healthy, environment-configured with the API's base
  URL (service-name-based inside the compose network, matching the
  existing `api`/`worker` pattern from sub-project 1).
- `docker compose up -d --build` brings up the entire stack —
  postgres, redis, api, worker, frontend — as one command, matching
  the requirement that "all services run seamlessly together."

## Future sub-projects (not in scope here)

- Auto-generated architecture diagrams in the middle panel
- Multi-repo workspace/dashboard polish
- Light mode / theme switching
