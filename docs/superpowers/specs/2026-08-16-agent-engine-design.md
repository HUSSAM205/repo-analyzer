# Repo Analyzer — Sub-Project 2A: Multi-Agent Chat Engine & Backend Extensions

Status: Approved
Date: 2026-08-16

## Purpose

Add a conversational agent that can answer questions about an analyzed
repo, explain its architecture, and cite exact files/symbols/line
numbers — built on top of the existing hybrid search core (sub-project
1). Also adds the two backend capabilities the frontend (sub-project
2B) will need: a file tree listing and full file content retrieval,
neither of which exist today (the analysis pipeline currently stores
only per-symbol chunks, not whole files, and the cloned repo is
deleted after processing).

This is a real product the user intends to run. Backend only —
verified via API calls and automated tests, no UI in this phase
(sub-project 2B builds the UI against this API).

## Non-goals (this sub-project)

- No frontend (Next.js UI is sub-project 2B)
- No true multi-agent graph with specialist sub-agents — a single
  agent with tool access, per the approved design decision
- No real end-to-end LLM run in automated tests — no API key exists
  yet; automated tests run against a deterministic fake LLM client.
  A real run against Anthropic/OpenAI is a manual smoke-test step
  once a key is added (documented in the README), same pattern as
  sub-project 1's Docker walkthrough
- No auto-generated architecture diagrams (Mermaid call-graphs) — the
  code viewer shows real syntax-highlighted source only; diagram
  generation needs import/call-graph extraction that doesn't exist
  yet and is out of scope here
- No message editing/deletion, no conversation renaming/sharing —
  conversations and messages are create/list/read only

## Architecture

### New capability 1: full file content storage

The existing ingestion worker (`app/workers/tasks.py`, `analyze_repo`)
clones a repo to a temp directory, walks it, chunks it per-symbol
(`app.core.chunker`), embeds each chunk, stores `CodeChunk` rows, then
deletes the temp clone. It never stores a file's full, unmodified
content — only whatever text ended up in each AST-derived chunk (which
drops module-level code like imports, per sub-project 1's known
limitations).

Add a `files` table populated during the same walk that produces
chunks, storing each file's full content once, so the frontend can
show real source after the temp clone is gone:

```
files(repo_id, path, content, created_at)
  UniqueConstraint(repo_id, path)
```

This is populated in `walk_and_chunk` (or a sibling pass called from
the same worker step) — for every file that's walked (whether or not
it produces AST symbols), store `(repo_id, relative_path, full_text)`
alongside the existing chunking. Binary/unreadable files are skipped
the same way they already are (existing `files_skipped` logic covers
this; no behavior change to that path).

On re-analysis (an existing repo being re-submitted), old `files` rows
for that `repo_id` are deleted and replaced in the same transaction as
the existing `CodeChunk` replace-on-reanalysis logic (sub-project 1's
final review fix, C2) — same atomicity guarantee: a mid-insert failure
rolls back to the previous state, not a half-populated table.

### New capability 2: file tree + file content API

- `GET /api/v1/repos/{repo_id}/files` — returns a tree structure built
  from the distinct `path` values in `files` for that repo, grouped by
  directory. Requires the requesting user to own the repo (404 if not,
  same pattern as every existing per-repo endpoint).
- `GET /api/v1/repos/{repo_id}/files/content?path=<relative_path>` —
  returns the stored full content for that one file. Same ownership
  check. 404 if the path doesn't exist for that repo.

### New capability 3: the agent engine

**LLM client layer** (`app/core/llm.py`): a small provider-agnostic
interface —

```python
class LLMClient(Protocol):
    async def stream_chat(
        self, messages: list[Message], tools: list[ToolSpec]
    ) -> AsyncIterator[LLMEvent]: ...
```

Two real implementations (`AnthropicClient`, `OpenAIClient`, selected
via `Settings.llm_provider`) and one test implementation
(`FakeLLMClient`) that yields a scripted sequence of `LLMEvent`s (text
tokens, tool calls, a final message) so agent-loop logic, tool wiring,
SSE streaming, and persistence are all fully testable without a real
API key. `LLMEvent` is a small tagged union: token, tool_call,
tool_result, done, error.

**Agent loop** (`app/core/agent.py`): a LangGraph `StateGraph` with
two nodes — `assistant` (calls the LLM client with the conversation
history + tool specs) and `tools` (executes any tool calls the
assistant emitted, feeds results back). Standard ReAct-style loop:
assistant → (if tool calls) → tools → assistant → ... → (no more tool
calls) → done. State is the running message list. The system prompt
instructs the model to cite `file_path:start_line-end_line` whenever
it references code, and to prefer calling `search_code` over guessing.

**Tools** (`app/core/agent_tools.py`): one tool, `search_code(query:
str) -> list[dict]`, a thin wrapper around the existing
`hybrid_search` (sub-project 1, unchanged) — takes a natural-language
query, returns ranked chunks with `file_path`, `symbol_name`,
`start_line`, `end_line`, `content`. This is the agent's only window
into repo content; it does not get raw DB or filesystem access.

### New capability 4: conversations API

```
conversations(id, repo_id, user_id, title, created_at)
messages(id, conversation_id, role, content, created_at)
  role: "user" | "assistant"
```

- `POST /api/v1/repos/{repo_id}/conversations` — create a new
  conversation for a repo (owner-only).
- `GET /api/v1/repos/{repo_id}/conversations` — list the user's
  conversations for that repo.
- `GET /api/v1/conversations/{id}/messages` — full message history
  (owner-only, checked via the conversation's `repo_id` → `Repo.user_id`).
- `POST /api/v1/conversations/{id}/messages` — send a user message,
  stream the assistant's response back via Server-Sent Events. The
  user message and the completed assistant message are both persisted
  to `messages` once the stream finishes (or, on an error mid-stream,
  the user message is persisted but no partial/broken assistant
  message is — the SSE stream instead emits an `error` event and the
  client can retry).

SSE event shape: `token` (incremental text), `tool_call` (agent is
searching — lets the UI show a "searching code..." indicator),
`tool_result` (search completed), `done` (final message persisted,
carries the saved message id), `error` (LLM/tool failure — human
readable message, never a raw exception or 500 status; the HTTP
response itself stays 200 with `text/event-stream`, since the error is
inside the stream, not the request).

## Data flow

1. Client creates a conversation (or resumes an existing one) for a
   repo it owns.
2. Client `POST`s a message to `/conversations/{id}/messages`.
3. Route loads conversation history from `messages`, appends the new
   user message, invokes the LangGraph agent loop with that history
   and the `search_code` tool spec.
4. Agent loop streams `LLMEvent`s; the route translates each into an
   SSE event and flushes it to the client immediately (no buffering
   the whole response).
5. When the loop reaches `done`, the route persists both the user
   message and the assistant's final message, then emits the SSE
   `done` event.
6. Any exception during steps 3-5 (LLM error, tool error, DB error
   after the user message was saved) is caught and converted to an
   SSE `error` event; the connection then closes normally.

## Error handling

- LLM API errors (auth failure, rate limit, timeout, malformed
  response) are caught inside the agent loop and surfaced as a single
  SSE `error` event with a human-readable message — never an
  unhandled exception that becomes a raw 500 mid-stream (the HTTP
  status line and headers are already sent by the time an LLM error
  can occur, so a 500 isn't possible at that point anyway; the
  handling here is about giving the client a clean, parseable signal
  instead of a truncated/hung connection).
- Tool-call failures (e.g. `search_code` hitting a DB error) are
  caught, converted into a `tool_result` event carrying an error
  description, and fed back into the agent's message history as an
  observation — the agent gets a chance to respond to the failure
  (e.g. "I wasn't able to search the code, but here's what I can tell
  you...") rather than the whole request failing.
- File-content/tree endpoints follow the exact ownership-check pattern
  already used by `/search` and `/jobs/{id}` (404, not 403, on
  mismatch — no existence leak).

## Testing

- Unit: `LLMClient` protocol conformance for `FakeLLMClient`; agent
  loop logic driven entirely by `FakeLLMClient` scripted event
  sequences (verifies the assistant↔tools loop terminates correctly,
  handles a multi-turn tool-call sequence, handles a tool error being
  fed back in); `search_code` tool wrapper against a mocked
  `hybrid_search` call.
- Integration: real Postgres + Redis, `FakeLLMClient` standing in for
  the real API — full conversation create → send message → SSE stream
  → verify persisted messages; file tree/content endpoints against
  real `files` rows; ownership-check tests (404 for non-owners) for
  every new endpoint, mirroring sub-project 1's pattern; re-analysis
  correctly replaces `files` rows (no duplication, mirroring the C2
  fix's test for `CodeChunk`).
- No live LLM API calls in any automated test (no key exists yet, and
  even once one does, automated tests stay on the fake client for
  determinism — this mirrors the "no live GitHub calls in tests"
  constraint from sub-project 1).
- Manual smoke test (documented in README, not automated): once a real
  API key is added, run one real conversation against a real repo to
  confirm the real `AnthropicClient`/`OpenAIClient` path works
  end-to-end — same spirit as sub-project 1's Docker walkthrough.

## Future sub-projects (not in scope here)

- 2B: Next.js frontend consuming this API (file tree, code viewer,
  chat panel, full Docker packaging)
- Later: auto-generated architecture diagrams (needs call-graph
  extraction), true multi-agent specialist graph (if single-agent
  proves insufficient in practice), conversation management (rename,
  delete, share)
