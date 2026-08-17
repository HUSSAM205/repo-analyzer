# Repo Analyzer — Sub-Project 3A: Public Access & Gemini Backend

Status: Approved
Date: 2026-08-17

## Purpose

Remove the login/registration wall so any visitor can analyze a repo and
chat about it with zero friction, and add Google Gemini as a third real
LLM provider alongside Anthropic and OpenAI. This is backend-only —
verified via API calls and automated tests. Sub-project 3B builds the
public-facing UI (no login screen, full visual redesign) against the API
this sub-project produces.

Approved design decisions carried in from brainstorming:
- **Guest identity, not no identity**: visitors get an auto-provisioned,
  invisible guest account (Approach A) rather than a fully anonymous
  model. This reuses the existing JWT + token-bucket rate-limiter
  infrastructure essentially unchanged, and keeps abuse protection
  cryptographically backed (a server-issued token) rather than something
  a visitor can reset by clearing cookies.
- **Fully public reads**: any analyzed repo, its files, and its
  conversations are viewable by anyone holding the URL/id, regardless of
  who submitted it — like a Gist link, not a private workspace. Writes
  (submitting a new repo, sending a chat message) still require *a*
  valid token (guest or real) so rate limiting keeps working.
- **`GET /api/v1/repos` (the list endpoint) stays personal** — it shows
  repos the calling guest/user originally submitted, not a global
  gallery. Individual repo pages remain reachable by anyone with the
  direct link even though they don't show up in another visitor's list.

## Non-goals (this sub-project)

- No visual/UI changes — sub-project 3B's job entirely.
- No CAPTCHA, IP-based throttling, or other abuse defense beyond the
  existing per-identity token bucket, now extended to chat. A guest
  identity is cheap to mint (one unauthenticated `POST`), so the token
  bucket bounds *sustained* abuse from a single guest cookie but not
  someone deliberately minting many guests — accepted as an MVP-scope
  limitation, same spirit as sub-project 1's existing rate-limit scope.
- No data retention/expiration policy for guest-created data — guest
  repos and conversations persist exactly like registered-user data
  always has. Cleanup, if ever needed, is a future concern.
- No removal of the existing registered-user auth endpoints
  (`/auth/register`, `/auth/login`, `/auth/api-keys`) — they stay working
  in the backend and in automated tests. Sub-project 3B simply never
  renders UI that calls them; nothing here forces their removal, and
  leaving them costs nothing.
- No migration tooling for pre-existing production data — this project
  has no production users yet, so the `repos` table's uniqueness-key
  change (below) does not need a data-migration story beyond "safe to
  apply to the current dev database."

## Architecture

### New capability 1: guest identity

`User` gains a `is_guest: bool` column (default `false`), and `email` /
`hashed_password` become nullable (a guest row has both `NULL`). The
existing `unique` index on `email` already tolerates multiple `NULL`s
under Postgres, so no constraint change needed there. Alembic migration
required.

`POST /api/v1/auth/guest` (new, unauthenticated, no request body):
creates a `User(is_guest=True, email=None, hashed_password=None)` and
returns a `TokenResponse` — byte-for-byte the same shape `/auth/login`
returns today. This is the only new backend endpoint in this
sub-project; everything else is either a relaxed check on an existing
endpoint or a new provider branch.

### New capability 2: public reads

Ownership checks are removed from every **read** path; every **write**
path keeps requiring a valid bearer token but no longer requires that
token to match the resource's creator:

| Endpoint | Today | After |
|---|---|---|
| `GET /repos/{repo_id}` (new — see below) | doesn't exist | repo existence only, `RepoResponse` |
| `GET /repos/{id}/files`, `.../files/content` | `get_owned_repo` (404 on mismatch) | repo existence only (404 if repo doesn't exist, no ownership check) |
| `GET /jobs/{id}` | inline `repo.user_id != current_user.id` | job existence only |
| `GET /search` | inline `repo.user_id != current_user.id` | repo existence only |
| `POST /repos/{repo_id}/conversations` (create) | `get_owned_repo` | repo existence only — anyone can start a new conversation thread on any analyzed repo |
| `GET /repos/{repo_id}/conversations` (list) | `get_owned_repo`, filtered to `Conversation.user_id == current_user.id` | repo existence only, filter removed — lists *all* conversations on that repo, not just the caller's |
| `GET /conversations/{id}/messages` | `get_owned_conversation` | conversation existence only |
| `POST /conversations/{id}/messages` (send chat) | `get_owned_conversation` | conversation existence only (still rate-limited, see below) |
| `GET /repos` (list) | `Repo.user_id == current_user.id` | **unchanged** — stays personal, per the approved design |
| `POST /repos/analyze` | rate-limited, creates repo scoped to `current_user.id` | rate-limited; see capability 3 for the dedup change |

`get_owned_repo`/`get_owned_conversation` in `app/api/deps.py` are
replaced by `get_repo_or_404`/`get_conversation_or_404` (existence-only,
same 404-not-403 no-existence-leak behavior, just without the
`user.id` comparison). Every call site above updates its import
accordingly. `current_user` stays a required dependency everywhere (a
guest token still has to be presented — this is what keeps the chat/
analyze rate limiter meaningful), it's just no longer compared against
resource ownership on reads.

**Gap found while designing 3B against this API**: no endpoint has ever
existed to fetch a single repo's metadata (name, status) by id — the
frontend's workspace page (`app/repos/[repoId]/page.tsx`) currently
works around this by fetching the caller's own `GET /repos` *list* and
filtering client-side for the matching id. Under public reads, that
would silently 404 a guest opening a repo link someone else submitted
(the exact "fully public by URL" scenario this sub-project exists to
support), since the list stays personal by design. Add
`GET /repos/{repo_id}` — same existence-only check as every other read
in this table, returns the existing `RepoResponse` shape. This is a
genuinely new endpoint (not a relaxed check on an existing one), but it
belongs in the same task as the rest of this capability since it uses
the exact `get_repo_or_404` helper this capability introduces.

### New capability 3: global repo dedup

Today, `Repo` is unique on `(user_id, url)` — two different users
analyzing the same public GitHub URL get two entirely separate `Repo`
rows, each independently cloned/chunked/embedded. Combined with public
access, this would mean every visitor pays the full analysis cost (and,
worse, a real Gemini API call cost once 3B ships) for popular repos
someone already analyzed minutes ago.

Change the uniqueness key to `url` alone (migration: drop
`uq_repo_user_url`, add a unique index on `url`). `POST /repos/analyze`
behavior changes to:

- No existing `Repo` for this URL → create it (`user_id` = the calling
  guest/user, for their personal list), create a `Job`, enqueue analysis
  — unchanged from today.
- Existing `Repo` with `status == READY` → return its `id` and its most
  recent `Job.id`. **No new `Job` is created, nothing is enqueued.** The
  frontend's existing poll-until-terminal flow works unchanged — it
  simply observes the job already at `COMPLETED`.
- Existing `Repo` with `status == PENDING` → same: return the existing
  `id`/latest `Job.id`, don't enqueue a duplicate. Multiple visitors
  submitting the same not-yet-finished URL all converge onto the one
  in-flight analysis.
- Existing `Repo` with `status == FAILED` → re-analyze: create a new
  `Job`, enqueue as today (existing replace-on-reanalysis logic for
  `CodeChunk`/`File` rows, from sub-project 2A, already handles this
  correctly and is unchanged).

`Repo.user_id` keeps its current meaning ("who originally submitted
this") for the personal list — it is not updated on a dedup hit. A guest
who submits an already-analyzed URL is redirected straight to the
existing repo via the response's `repo_id` but won't see it appear in
their own `GET /repos` list, since they didn't originate it. Accepted as
a reasonable MVP tradeoff — a "recently viewed" list is a natural, small
follow-up if it's ever wanted, not required now.

### New capability 4: chat rate limiting

`POST /conversations/{id}/messages` is currently **unlimited** — the
existing token bucket only guards `/repos/analyze`. With a real,
per-message-billed Gemini key sitting behind a now-authless-feeling
frontend, this is the actual cost-control backstop. Add
`enforce_chat_rate_limit` (mirrors `enforce_analyze_rate_limit` exactly,
same Lua token-bucket, different Redis key prefix
`rate_limit:chat:{user_id}`), new settings
`rate_limit_chat_per_minute: int = 15` /
reuses the existing `rate_limit_bucket_capacity`. Applied as a
dependency on `send_message` in `chat.py`, replacing its plain
`get_current_user` dependency (same pattern `analyze_repo_endpoint`
already uses).

### New capability 5: Gemini provider

`backend/app/core/llm_providers.py` gains `GeminiClient`, implementing
the existing `LLMClient` protocol exactly like `AnthropicClient` and
`OpenAIClient` do — manual streaming + manual tool-call extraction, not
the SDK's higher-level "automatic function calling" convenience wrapper,
so tool-call events flow through our own `LLMEvent`/`ToolCall` types and
our own LangGraph agent loop stays the single place that decides when to
call `search_code`.

Uses the `google-genai` package (the current official SDK — the older
`google-generativeai` package is deprecated). Message-format translation
mirrors `_to_anthropic_messages`/`_to_openai_messages`: Gemini uses
`"user"`/`"model"` roles (not `"assistant"`) and represents tool
results as `function_response` parts keyed by function name, not a
tool-call id — the translation function looks up the matching call by
name from the preceding turn rather than by id. Streaming via
`client.aio.models.generate_content_stream(...)`; text parts become
`token` events, a `function_call` part becomes a `tool_call` event
(there is normally at most one per turn in practice, but the code
handles a list for consistency with the other two clients), completion
with no function call becomes `message_done`. Errors follow the exact
`AnthropicClient`/`OpenAIClient` pattern: `logger.exception(...)` with
the real error server-side, a generic `_PROVIDER_ERROR_MESSAGE` over SSE
— never leak Gemini's raw error body (which can include request
internals) to the client.

`Settings.llm_provider` becomes
`Literal["anthropic", "openai", "gemini", "fake"]`. New settings
`gemini_api_key: str | None = None`, `gemini_model: str = "gemini-3.7-flash"`
(verified against Google's current model docs at spec-writing time —
`gemini-2.0-flash` and earlier are explicitly deprecated/shutting down;
`gemini-3.7-flash` is the current recommended general-purpose default.
If this has changed again by implementation time, confirm the current
default rather than trusting this spec, and update it here too).
`get_llm_client()` gains a `gemini` branch matching the existing
`if not current_settings.gemini_api_key: raise RuntimeError(...)`
pattern. `docker-compose.yml`'s existing LLM env-passthrough block (both
`api` and `worker` services, added in sub-project 2B Task 11) gains
`GEMINI_API_KEY`/`GEMINI_MODEL` alongside the existing five lines. Root
`.env.example` gains the same two keys.

A real `GEMINI_API_KEY` is already available (provided during
brainstorming, stashed in the gitignored `backend/.env` — never
committed, never printed). Its format doesn't match the usual Google AI
Studio shape, so the implementation task includes one live smoke-test
call against the real Gemini API early, specifically to confirm the key
authenticates, before building the rest of the client around an
unverified assumption.

## Data flow (guest bootstrap)

1. A visitor's first request to any BFF route (sub-project 3B) arrives
   with no session cookie.
2. The BFF layer calls `POST /api/v1/auth/guest`, gets a token back,
   sets it in the same httpOnly session cookie `lib/session.ts` already
   manages — this is 3B's job to wire, described here only because it's
   the consumer of this sub-project's new endpoint.
3. Every subsequent request in that browser proxies through with that
   guest token, indistinguishable from a real logged-in user's token to
   every backend endpoint except the ones this sub-project explicitly
   relaxes.

## Error handling

- Every relaxed endpoint keeps its exact 404-not-403 shape on
  nonexistent resources — only the *ownership* comparison is removed,
  not the existence check, so there's still no way to distinguish "not
  yours" from "doesn't exist" (moot now that nothing is "not yours" to
  read, but keeps the response shape stable for 3B's error handling).
- Gemini client errors follow the identical caught-and-generic-message
  pattern as the other two providers (see capability 5) — no new error
  surface for the SSE stream to handle.
- Chat rate-limit rejection reuses the existing 429 shape
  (`enforce_analyze_rate_limit`'s `HTTPException` pattern), so the
  frontend's existing 429 handling (if any) or the natural fetch-error
  path in 3B covers it without new client-side error types.

## Testing

- Unit: `GeminiClient.stream_chat` against a mocked `google-genai`
  client — token streaming, single tool-call turn, multi-tool-call
  handling, error path (mirrors existing `AnthropicClient`/
  `OpenAIClient` unit test structure exactly). Message/role translation
  function tested directly for both plain-text and tool-result turns.
- Integration: real Postgres + Redis, `FakeLLMClient` — guest endpoint
  creates a usable token; every relaxed endpoint accessible cross-guest
  (guest A creates a repo/conversation, guest B reads it successfully);
  `GET /repos` list stays scoped to the caller even when another guest's
  repo exists; dedup behavior for all three `Repo.status` cases
  (READY/PENDING/FAILED) — no duplicate `Job` created on a READY/PENDING
  hit, re-analysis triggered on a FAILED hit; chat rate limit rejects
  past the configured bucket capacity.
- No live Gemini API calls in automated tests — same "fake provider for
  determinism" constraint as Anthropic/OpenAI today.
- Manual smoke test (documented in README): one real conversation
  against the real Gemini API using the configured key, confirming
  auth + streaming + tool-calling all work end-to-end — same pattern as
  sub-project 2A's Anthropic/OpenAI smoke test.

## Future sub-projects (not in scope here)

- 3B: public-facing frontend (no login UI, guest-session bootstrap,
  full Linear/Raycast/Cursor-style visual redesign) consuming this API.
- Later: a lightweight "recently viewed" list for guests who hit a
  dedup on submission; IP-based or CAPTCHA-based defense against guest
  minting abuse, if it becomes a real problem in practice.
