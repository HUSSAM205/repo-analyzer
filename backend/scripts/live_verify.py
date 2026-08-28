#!/usr/bin/env python3
"""Live end-to-end verification against a deployed instance of this app.

Exercises the actual public surface (the Next.js frontend's proxy routes,
not the FastAPI backend directly) exactly as a real browser would:

  1. Ingest a real GitHub repository, wait for analysis to complete, and
     verify it produced a real classification (not "Unclassified") and a
     non-empty ELI10 beginner summary.
  2. Fetch and verify raw file content for at least 3 files.
  3. Send 5 distinct technical chat messages, asserting each streams back a
     substantive response with no raw "error" SSE event.
  4. Call every flagship tool endpoint and verify each returns valid data.

Exits 0 only if every check passes. Intended as a release gate: only
commit/deploy once this has passed against the live target.

Usage:
    python backend/scripts/live_verify.py [base_url]

    base_url defaults to https://repo-analyzer-app.vercel.app
"""

import json
import sys
import time
import uuid

import httpx

DEFAULT_BASE_URL = "https://repo-analyzer-app.vercel.app"
# A small, real, public repo not already cached by prior runs of this
# script -- guarantees a genuine fresh clone+parse+store pipeline run
# rather than converging onto an existing analysis. Analysis (including
# domain_briefing classification) only ever runs ONCE per repo URL and is
# cached permanently -- change this to a never-before-used URL if a prior
# run already analyzed the current value (submitting the same URL again
# just converges onto that old, possibly-stale-from-an-older-code-version
# result instead of exercising the pipeline for real).
TEST_REPO_URL = "https://github.com/tiangolo/typer"
JOB_POLL_TIMEOUT_SECONDS = 120
JOB_POLL_INTERVAL_SECONDS = 2
CHAT_QUERIES = [
    "Where is the primary entry point and how is the app bootstrapped?",
    "Trace the end-to-end data lifecycle for a core request.",
    "How is global error handling and exception logging implemented?",
    "Provide the exact code pattern and steps to add a new API route.",
    "How are environment variables and security tokens managed?",
    "Detail the database schema, models, and relational constraints.",
    "Identify the top 3 architectural bottlenecks and high technical debt files.",
]
FLAGSHIP_ENDPOINTS = ["readme", "security-scan", "health-score", "quiz", "flow-map", "tech-debt", "compliance-scan"]

_PASS = "PASS"
_FAIL = "FAIL"


class VerificationFailure(Exception):
    pass


def _report(step: str, ok: bool, detail: str = "") -> None:
    status = _PASS if ok else _FAIL
    line = f"[{status}] {step}"
    if detail:
        line += f" -- {detail}"
    print(line, flush=True)
    if not ok:
        raise VerificationFailure(f"{step}: {detail}")


def _parse_sse_events(raw: str) -> list[dict]:
    events = []
    for block in raw.strip().split("\n\n"):
        if not block.strip():
            continue
        lines = block.strip().split("\n")
        event_type = lines[0].removeprefix("event: ")
        data = json.loads(lines[1].removeprefix("data: "))
        events.append({"type": event_type, "data": data})
    return events


def run(base_url: str) -> None:
    client = httpx.Client(base_url=base_url, timeout=60.0, follow_redirects=True)

    print(f"=== Live verification against {base_url} ===\n")

    # --- Step 0: establish a session (middleware mints a guest token on
    # the first request with no session cookie) --------------------------
    resp = client.get("/")
    _report("Establish session", resp.status_code == 200, f"GET / -> {resp.status_code}")

    # --- Step 1: ingest a live repository --------------------------------
    resp = client.post("/api/repos", json={"repo_url": TEST_REPO_URL})
    _report(
        "Submit repo for analysis", resp.status_code == 202,
        f"POST /api/repos -> {resp.status_code}: {resp.text[:300]}",
    )
    body = resp.json()
    repo_id, job_id = body["repo_id"], body["job_id"]
    print(f"       repo_id={repo_id} job_id={job_id}")

    deadline = time.monotonic() + JOB_POLL_TIMEOUT_SECONDS
    job_status = None
    while time.monotonic() < deadline:
        job_resp = client.get(f"/api/jobs/{job_id}")
        job_status = job_resp.json()
        if job_status["status"] in ("completed", "failed"):
            break
        time.sleep(JOB_POLL_INTERVAL_SECONDS)
    _report(
        "Repo analysis completes", job_status is not None and job_status["status"] == "completed",
        f"final job status: {job_status}",
    )
    print(f"       finished in ~{job_status['finished_at']}, skipped_files={job_status['skipped_files']}")

    # --- Step 1b: verify real classification + non-empty ELI10 -----------
    repo_resp = client.get(f"/api/repos/{repo_id}")
    _report("Fetch repo detail", repo_resp.status_code == 200, f"-> {repo_resp.status_code}")
    briefing = repo_resp.json().get("domain_briefing") or {}
    primary_field = briefing.get("primary_field")
    _report(
        "Repo classification is not 'Unclassified'", primary_field not in (None, "", "Unclassified"),
        f"primary_field={primary_field!r}",
    )
    beginner_summary = briefing.get("beginner_summary")
    _report(
        "ELI10 beginner summary is non-empty", bool(beginner_summary and beginner_summary.strip()),
        f"beginner_summary={beginner_summary!r}",
    )

    # --- Step 2: verify raw file content for >= 3 files ------------------
    tree_resp = client.get(f"/api/repos/{repo_id}/files")
    _report("Fetch file tree", tree_resp.status_code == 200, f"-> {tree_resp.status_code}")

    def _flatten(entries: list[dict]) -> list[str]:
        paths = []
        for entry in entries:
            if entry["type"] == "file":
                paths.append(entry["path"])
            elif entry["children"]:
                paths.extend(_flatten(entry["children"]))
        return paths

    all_paths = _flatten(tree_resp.json()["entries"])
    _report("File tree is non-empty", len(all_paths) >= 3, f"found {len(all_paths)} files")

    verified_files = 0
    for path in all_paths[:5]:
        content_resp = client.get(f"/api/repos/{repo_id}/files/content", params={"path": path})
        if content_resp.status_code == 200 and len(content_resp.json().get("content", "")) > 0:
            verified_files += 1
    _report(
        "Raw content verified for >= 3 files", verified_files >= 3,
        f"verified {verified_files}/{min(5, len(all_paths))} sampled files",
    )

    # --- Step 3: 10 consecutive chat queries -----------------------------
    conv_resp = client.post(f"/api/repos/{repo_id}/conversations", json={"title": "Live verification"})
    _report("Create conversation", conv_resp.status_code == 201, f"-> {conv_resp.status_code}: {conv_resp.text[:300]}")
    conversation_id = conv_resp.json()["id"]

    total = len(CHAT_QUERIES)
    degraded_turns = 0
    for i, query in enumerate(CHAT_QUERIES, start=1):
        with client.stream(
            "POST", f"/api/conversations/{conversation_id}/messages", json={"content": query}
        ) as stream_resp:
            _report(f"Chat turn {i}/{total} returns 200", stream_resp.status_code == 200, f"query={query!r}")
            raw = "".join(stream_resp.iter_text())
        events = _parse_sse_events(raw)
        has_error = any(e["type"] == "error" for e in events)
        ends_in_done = bool(events) and events[-1]["type"] == "done"
        response_text = "".join(e["data"].get("text", "") for e in events if e["type"] == "token")
        substantive = len(response_text.strip()) >= 10
        _report(
            f"Chat turn {i}/{total} is substantive, no error event",
            not has_error and ends_in_done and substantive,
            f"has_error={has_error} ends_in_done={ends_in_done} response_len={len(response_text)}",
        )
        # A response can be non-error and substantive while still NOT being a
        # real AI answer -- chat.py's _graceful_degraded_reply falls back to
        # deterministic_answer.py's keyword-matched Tier 3 reply (this exact
        # marker string) when both configured Groq models fail. That's a
        # legitimate "unbreakable" success (no crash, no error shown), but
        # it is NOT a code-grounded AI answer -- reported separately (never
        # as a FAIL) so a run doesn't silently look like "100% real AI"
        # when it was actually "100% keyword fallback".
        if "temporarily unable to reach the AI provider" in response_text:
            degraded_turns += 1
    if degraded_turns:
        print(
            f"[INFO] {degraded_turns}/{total} chat turns used the Tier 3 deterministic "
            "fallback (no live AI reachable at request time), not a real AI answer -- "
            "graceful, not a failure, but worth knowing.",
            flush=True,
        )

    # --- Step 4: every flagship tool endpoint ----------------------------
    for tool in FLAGSHIP_ENDPOINTS:
        tool_resp = client.get(f"/api/repos/{repo_id}/{tool}")
        ok = tool_resp.status_code == 200
        body_ok = False
        if ok:
            try:
                data = tool_resp.json()
                body_ok = isinstance(data, dict) and len(data) > 0
            except json.JSONDecodeError:
                body_ok = False
        _report(
            f"Flagship tool /{tool} returns valid data", ok and body_ok,
            f"-> {tool_resp.status_code}: {tool_resp.text[:200]}",
        )

    print(f"\n=== All checks passed against {base_url} ===")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_URL
    try:
        run(target)
    except VerificationFailure as exc:
        print(f"\n=== VERIFICATION FAILED: {exc} ===")
        sys.exit(1)
    except Exception as exc:
        print(f"\n=== VERIFICATION CRASHED: {type(exc).__name__}: {exc} ===")
        sys.exit(1)
