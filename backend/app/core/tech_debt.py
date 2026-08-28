import json
import logging

from app.core.llm import LLMClient, Message
from app.core.token_budget import MAX_CONTEXT_CHARS, sanitize_context
from app.db.models import File

logger = logging.getLogger(__name__)

_MAX_SAMPLE_FILES = 12
_MAX_FILE_CHARS = 3000
_MAX_ITEMS = 6

_SKIP_SUFFIXES = (
    ".lock", ".min.js", ".min.css", ".map", ".svg", ".png", ".jpg", ".jpeg",
    ".gif", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".pdf", ".zip",
)
_SKIP_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "uv.lock", "poetry.lock"}

_SYSTEM_PROMPT = (
    "You are a senior engineer estimating technical debt for a code repository "
    "and proposing concrete refactors, in the style of a paid code-quality "
    "audit. Only flag issues you can point to real evidence for in the code "
    "you were shown -- never invent files or code you weren't given. Respond "
    "with strict JSON only -- no markdown code fences, no commentary, no text "
    "before or after the JSON. The JSON object must have exactly these keys:\n"
    "\"summary\" (2-3 sentences giving an overall technical-debt assessment of "
    "this codebase),\n"
    "\"items\" (a JSON array of up to 6 objects, each a specific, actionable "
    "refactor recipe, ordered highest-ROI first -- each object has exactly: "
    "\"file\" (the exact file path), \"issue\" (a short one-line description "
    "of the debt -- e.g. duplicated logic, a god function, missing "
    "abstraction, tight coupling), \"estimated_hours\" (a realistic number of "
    "engineer-hours to fix THIS one item, as a number), \"before_snippet\" (a "
    "short real excerpt, 3-15 lines, copied from the actual file showing the "
    "problem), \"after_snippet\" (a rewritten version of that same excerpt "
    "showing the fix -- must be a real, syntactically plausible improvement, "
    "not a vague placeholder), and \"explanation\" (1-2 sentences on why the "
    "after version is better and what it costs to leave as-is). Return an "
    "empty array if the code genuinely looks clean -- do not invent debt just "
    "to have something to report."
)


def _is_scannable(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if name in _SKIP_NAMES:
        return False
    return not path.lower().endswith(_SKIP_SUFFIXES)


def _pick_sample_files(files: list[File]) -> list[File]:
    return [f for f in files if _is_scannable(f.path)][:_MAX_SAMPLE_FILES]


def _build_prompt(files: list[File]) -> str:
    parts: list[str] = ["Source files to review for technical debt:"]
    budget = MAX_CONTEXT_CHARS
    for f in _pick_sample_files(files):
        snippet = sanitize_context(f.content[:_MAX_FILE_CHARS])
        block = f"--- {f.path} ---\n{snippet}\n"
        if len(block) > budget:
            break
        parts.append(block)
        budget -= len(block)
    return "\n".join(parts)


def _parse_response(text: str) -> dict | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped[3:]
        if stripped[:4].lower() == "json":
            stripped = stripped[4:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()

    parsed = json.loads(stripped)
    if not isinstance(parsed, dict) or "summary" not in parsed:
        raise ValueError("LLM response missing required 'summary' key")

    raw_items = parsed.get("items")
    items: list[dict] = []
    if isinstance(raw_items, list):
        for item in raw_items[:_MAX_ITEMS]:
            if not isinstance(item, dict):
                continue
            file_path = item.get("file")
            issue = item.get("issue")
            hours = item.get("estimated_hours")
            before = item.get("before_snippet")
            after = item.get("after_snippet")
            explanation = item.get("explanation")
            if not (file_path and issue and before and after and explanation):
                continue
            if not isinstance(hours, (int, float)):
                continue
            items.append({
                "file": str(file_path),
                "issue": str(issue),
                "estimated_hours": float(hours),
                "before_snippet": str(before),
                "after_snippet": str(after),
                "explanation": str(explanation),
            })

    return {
        "summary": str(parsed["summary"]),
        # Summed from the individual items rather than trusting a
        # separately-stated total from the model -- keeps the headline
        # number consistent with what's actually listed below it, even if
        # the model's own arithmetic (or JSON formatting) for a top-level
        # total field is off.
        "estimated_debt_hours": round(sum(item["estimated_hours"] for item in items), 1),
        "items": items,
    }


_LARGE_FILE_LINE_THRESHOLD = 400
_MAX_LARGE_FILE_ITEMS = 4
_TEST_PATH_HINTS = ("test", "spec", "__tests__")
_CI_PATH_HINTS = (".github/workflows/", ".gitlab-ci.yml", ".circleci/", "azure-pipelines.yml", "Jenkinsfile")
_DETERMINISTIC_SUMMARY = (
    "AI-based analysis is temporarily unavailable, so this is a deterministic, "
    "heuristic-only assessment (file size, test/CI presence) rather than a full "
    "code review -- refresh later for AI-generated refactor recipes."
)


def build_deterministic_tech_debt_report(files: list[File]) -> dict:
    """A best-effort debt report using only cheap, deterministic signals --
    no LLM call, so it's always available. Used as the fallback when
    generate_tech_debt_report's real analysis can't be produced (provider
    exhausted/erroring), so a viewer gets a genuinely useful (if shallow)
    report instead of a 503. Never fails, and (honestly) never fabricates
    a specific before/after code recipe the way the AI version does --
    each item says what the signal is, not a guessed fix.
    """
    items: list[dict] = []

    large_files = sorted(
        (f for f in files if f.content.count("\n") > _LARGE_FILE_LINE_THRESHOLD),
        key=lambda f: f.content.count("\n"),
        reverse=True,
    )
    for f in large_files[:_MAX_LARGE_FILE_ITEMS]:
        line_count = f.content.count("\n") + 1
        items.append({
            "file": f.path,
            "issue": f"Large file ({line_count} lines) -- a candidate for splitting into smaller, focused modules.",
            "estimated_hours": round(min(8.0, line_count / 150), 1),
            "before_snippet": f"# {f.path}: {line_count} lines in one file",
            "after_snippet": "# Split by responsibility into smaller, focused modules\n# (e.g. one file per class or feature area)",
            "explanation": "Based on line count alone, not a semantic review -- a large file is harder to navigate, review, and test in isolation.",
        })

    if not any(hint in f.path.lower() for f in files for hint in _TEST_PATH_HINTS):
        items.append({
            "file": "(repository-wide)",
            "issue": "No test files detected.",
            "estimated_hours": 8.0,
            "before_snippet": "# no test suite found in this repository",
            "after_snippet": "# add unit tests for core modules, wired into CI",
            "explanation": "Without automated tests, every change risks an undetected regression.",
        })

    if not any(hint in f.path.lower() for f in files for hint in _CI_PATH_HINTS):
        items.append({
            "file": "(repository-wide)",
            "issue": "No CI configuration detected.",
            "estimated_hours": 2.0,
            "before_snippet": "# no CI workflow found (.github/workflows, etc.)",
            "after_snippet": "# add a CI workflow that runs tests/lint on every push",
            "explanation": "Without CI, broken code can be merged without ever running the test suite.",
        })

    return {
        "summary": _DETERMINISTIC_SUMMARY,
        "items": items,
        "estimated_debt_hours": round(sum(item["estimated_hours"] for item in items), 1),
    }


async def generate_tech_debt_report(files: list[File], llm_client: LLMClient) -> dict | None:
    """Estimates technical debt and proposes before/after refactor recipes
    for a sample of the repo's files. Returns None on any failure (never
    raises) so the caller does not cache a broken result. A genuinely clean
    codebase (empty `items`, `estimated_debt_hours` 0.0) is a valid,
    cacheable success -- distinct from None.
    """
    if not files:
        return None

    prompt = _build_prompt(files)
    if not prompt.strip():
        return None

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

        return _parse_response(accumulated)
    except Exception:
        logger.warning("Tech-debt report generation failed", exc_info=True)
        return None
