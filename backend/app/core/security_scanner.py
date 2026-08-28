import json
import logging

from app.core.compliance_scanner import run_compliance_scan
from app.core.llm import LLMClient, Message
from app.core.token_budget import MAX_CONTEXT_CHARS, sanitize_context
from app.db.models import File

logger = logging.getLogger(__name__)

_MAX_SAMPLE_FILES = 15
_MAX_FILE_CHARS = 4000
_MAX_FINDINGS = 25

_VALID_SEVERITIES = {"critical", "high", "medium", "low"}
_VALID_CATEGORIES = {"security", "bug", "anti_pattern"}

# Skip binary-ish/generated/lock files entirely -- never real signal for a
# bug/security review, and lock files in particular can be enormous,
# wasting the whole sample budget on one file.
_SKIP_SUFFIXES = (
    ".lock", ".min.js", ".min.css", ".map", ".svg", ".png", ".jpg", ".jpeg",
    ".gif", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".pdf", ".zip",
)
_SKIP_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "uv.lock", "poetry.lock"}

_SYSTEM_PROMPT = (
    "You are a careful static-analysis reviewer scanning source code for "
    "real, concrete bugs, anti-patterns, and security vulnerabilities. Only "
    "report issues you can point to actual evidence for in the code you "
    "were shown -- never speculate about files you weren't given. Respond "
    "with strict JSON only -- no markdown code fences, no commentary, no "
    "text before or after the JSON. The response must be a JSON array. "
    "Each element must have exactly these keys: \"severity\" (one of "
    "\"critical\", \"high\", \"medium\", \"low\"), \"category\" (one of "
    "\"security\", \"bug\", \"anti_pattern\"), \"file\" (the exact file path "
    "you saw it in), \"line\" (the integer line number the issue starts at, "
    "or null if it applies to the whole file), \"title\" (a short one-line "
    "summary), and \"description\" (1-3 sentences explaining the issue and, "
    "if there's an obvious fix, how to address it). Return an empty array "
    "if you genuinely find nothing notable -- do not invent issues just to "
    "have something to report."
)


def _is_scannable(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if name in _SKIP_NAMES:
        return False
    return not path.lower().endswith(_SKIP_SUFFIXES)


def _pick_sample_files(files: list[File]) -> list[File]:
    return [f for f in files if _is_scannable(f.path)][:_MAX_SAMPLE_FILES]


def _build_prompt(files: list[File]) -> str:
    parts: list[str] = ["Source files to review:"]
    budget = MAX_CONTEXT_CHARS
    for f in _pick_sample_files(files):
        snippet = sanitize_context(f.content[:_MAX_FILE_CHARS])
        block = f"--- {f.path} ---\n{snippet}\n"
        if len(block) > budget:
            break
        parts.append(block)
        budget -= len(block)
    return "\n".join(parts)


def _parse_findings(text: str) -> list[dict]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped[3:]
        if stripped[:4].lower() == "json":
            stripped = stripped[4:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()

    parsed = json.loads(stripped)
    if not isinstance(parsed, list):
        raise ValueError("LLM response was not a JSON array")

    findings: list[dict] = []
    for item in parsed[:_MAX_FINDINGS]:
        if not isinstance(item, dict):
            continue
        severity = item.get("severity")
        category = item.get("category")
        title = item.get("title")
        description = item.get("description")
        file_path = item.get("file")
        if severity not in _VALID_SEVERITIES or category not in _VALID_CATEGORIES:
            continue
        if not title or not description or not file_path:
            continue
        line = item.get("line")
        findings.append({
            "severity": severity,
            "category": category,
            "file": str(file_path),
            "line": int(line) if isinstance(line, (int, float)) else None,
            "title": str(title),
            "description": str(description),
        })
    return findings


def build_deterministic_findings(files: list[File]) -> list[dict]:
    """A best-effort findings list -- no LLM call, so it's always
    available. Used as the fallback when scan_for_issues's real AI review
    (bugs, anti-patterns, AND secrets) can't be produced (provider
    exhausted/erroring), so a viewer gets real findings instead of a 503.

    Only ever reports secret-leak matches (reusing compliance_scanner.py's
    deterministic, regex-based detector) -- deliberately does not attempt
    to fabricate "bugs" or "anti-patterns" without a model's semantic
    judgment, the same honesty principle as tech_debt.py's fallback. An
    empty list here is a genuine, valid "no secrets found" result, not a
    failure -- the caller caches it exactly like a real scan.
    """
    secret_findings = run_compliance_scan(files)["secret_findings"]
    return [
        {
            "severity": "high",
            "category": "security",
            "file": f["file"],
            "line": f["line"],
            "title": f"Potential secret exposure: {f['pattern']}",
            "description": (
                f"Pattern-based match ({f['pattern']}) found a likely hardcoded secret: {f['preview']}. "
                "AI-based bug/anti-pattern review is temporarily unavailable, so this deterministic "
                "secret scan is the only finding type included right now."
            ),
        }
        for f in secret_findings
    ]


async def scan_for_issues(files: list[File], llm_client: LLMClient) -> list[dict] | None:
    """Scans a sample of the repo's files for bugs, anti-patterns, and
    security issues. Returns None on any failure (never raises) so the
    caller does not cache a broken/empty-due-to-error result -- an
    genuinely empty, successfully-parsed `[]` (no issues found) is a valid,
    cacheable result and is distinct from None (failure).
    """
    if not files:
        return None

    prompt = _build_prompt(files)
    if not prompt.strip():
        return []

    try:
        accumulated = ""
        llm_error: str | None = None
        async for event in llm_client.stream_chat(
            [Message(role="user", content=prompt)], tools=[], system_prompt=_SYSTEM_PROMPT
        ):
            if event.type == "token":
                accumulated += event.token or ""
            elif event.type == "error":
                llm_error = event.error

        if llm_error is not None:
            raise RuntimeError(f"LLM provider returned an error: {llm_error}")

        return _parse_findings(accumulated)
    except Exception:
        logger.warning("Security/bug scan failed", exc_info=True)
        return None
