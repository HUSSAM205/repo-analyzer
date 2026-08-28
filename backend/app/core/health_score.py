import json
import logging

from app.core.llm import LLMClient, Message
from app.core.token_budget import MAX_CONTEXT_CHARS, sanitize_context
from app.db.models import File

logger = logging.getLogger(__name__)

_MAX_SAMPLE_FILES = 10
_MAX_FILE_CHARS = 2500

_CI_PATH_HINTS = (".github/workflows/", ".gitlab-ci.yml", ".circleci/", "azure-pipelines.yml", "Jenkinsfile")
_TEST_PATH_HINTS = ("test", "spec", "__tests__")
_README_NAMES = ("readme.md", "readme.rst", "readme.txt", "readme")
_LICENSE_NAMES = ("license", "license.md", "license.txt", "copying")

_SYSTEM_PROMPT = (
    "You are assessing the code quality and consistency of a repository "
    "from a sample of its source files -- naming conventions, function/file "
    "length and complexity, error handling, and consistency of style. "
    "Respond with strict JSON only -- no markdown code fences, no "
    "commentary, no text before or after the JSON object. The JSON object "
    "must have exactly these keys: \"quality_score\" (an integer 0-100, "
    "where 100 is exceptionally clean, consistent, well-factored code and "
    "0 is deeply problematic) and \"commentary\" (2-3 sentences explaining "
    "the score, citing specific patterns you actually observed -- not "
    "generic advice)."
)


def _has_any(files: list[File], hints: tuple[str, ...]) -> bool:
    return any(hint in f.path.lower() for f in files for hint in hints)


def _deterministic_scores(files: list[File]) -> dict:
    total = len(files) or 1

    has_readme = any("/" not in f.path and f.path.lower() in _README_NAMES for f in files)
    readme_file = next((f for f in files if "/" not in f.path and f.path.lower() in _README_NAMES), None)
    readme_substantial = bool(readme_file and len(readme_file.content) > 500)
    documentation_score = (60 if has_readme else 0) + (40 if readme_substantial else 0)

    test_files = [f for f in files if any(hint in f.path.lower() for hint in _TEST_PATH_HINTS)]
    test_ratio = len(test_files) / total
    # A 10% test-file ratio already reads as "this project has real test
    # coverage" for a typical repo -- scale linearly up to that point, cap
    # at 100 rather than reward test-file-heavy repos beyond full marks.
    testing_score = min(100, round((test_ratio / 0.10) * 100)) if test_files else 0

    has_ci = _has_any(files, _CI_PATH_HINTS)
    has_docker = any(f.path.rsplit("/", 1)[-1] in ("Dockerfile", "docker-compose.yml", "docker-compose.yaml") for f in files)
    automation_score = (70 if has_ci else 0) + (30 if has_docker else 0)

    has_license = any("/" not in f.path and f.path.lower() in _LICENSE_NAMES for f in files)

    return {
        "documentation_score": documentation_score,
        "testing_score": testing_score,
        "automation_score": automation_score,
        "has_readme": has_readme,
        "has_tests": bool(test_files),
        "has_ci": has_ci,
        "has_license": has_license,
    }


def _pick_sample_files(files: list[File]) -> list[File]:
    # Bias toward files that look like real source (skip lock/manifest
    # files, which say nothing about code quality) -- reuses the same
    # "not obviously non-source" filter as security_scanner would, kept
    # inline here since the exact exclusion list differs slightly (this
    # scorer cares about code files specifically, not "anything reviewable").
    source_like = [f for f in files if "." in f.path.rsplit("/", 1)[-1] and not f.path.endswith((".lock", ".md", ".json", ".yml", ".yaml", ".txt"))]
    return (source_like or files)[:_MAX_SAMPLE_FILES]


def _build_prompt(files: list[File]) -> str:
    parts = ["Sampled source files:"]
    budget = MAX_CONTEXT_CHARS
    for f in _pick_sample_files(files):
        snippet = sanitize_context(f.content[:_MAX_FILE_CHARS])
        block = f"--- {f.path} ---\n{snippet}\n"
        if len(block) > budget:
            break
        parts.append(block)
        budget -= len(block)
    return "\n".join(parts)


def _parse_quality(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped[3:]
        if stripped[:4].lower() == "json":
            stripped = stripped[4:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("LLM response was not a JSON object")
    score = int(parsed["quality_score"])
    return {"quality_score": max(0, min(100, score)), "commentary": str(parsed["commentary"])}


# Used only when the LLM-based quality assessment is unavailable -- a
# neutral midpoint rather than a guess, paired with commentary that says so
# plainly. The other three sub-scores stay fully accurate either way, since
# they never depended on the LLM in the first place.
_FALLBACK_QUALITY_SCORE = 50
_FALLBACK_QUALITY_COMMENTARY = (
    "Code-quality assessment needs AI and is temporarily unavailable, so this sub-score is a neutral "
    "placeholder -- documentation, testing, and automation above are unaffected (they're measured "
    "directly from the repo, not by the AI)."
)


async def compute_health_score(files: list[File], llm_client: LLMClient) -> dict | None:
    """Computes a 0-100 maintainability score for the repo.

    Documentation/testing/automation sub-scores are purely deterministic
    (README presence/size, test-file ratio, CI/Docker config presence) and
    never depend on the LLM -- only `quality_score` (code cleanliness/
    consistency, which genuinely needs a model to judge) does. If that LLM
    call fails, `quality` falls back to a neutral, clearly-labeled
    placeholder (see _FALLBACK_QUALITY_SCORE) rather than failing the whole
    scorecard -- a viewer still gets three real, accurate sub-scores instead
    of a 503. Returns None only when there's nothing to score at all (no
    files), which the caller still doesn't cache.
    """
    if not files:
        return None

    deterministic = _deterministic_scores(files)
    prompt = _build_prompt(files)

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

        quality = _parse_quality(accumulated)
    except Exception:
        logger.warning("Health score quality assessment failed -- using neutral placeholder", exc_info=True)
        quality = {"quality_score": _FALLBACK_QUALITY_SCORE, "commentary": _FALLBACK_QUALITY_COMMENTARY}

    sub_scores = {
        "documentation": deterministic["documentation_score"],
        "testing": deterministic["testing_score"],
        "automation": deterministic["automation_score"],
        "quality": quality["quality_score"],
    }
    overall = round(sum(sub_scores.values()) / len(sub_scores))

    return {
        "overall_score": overall,
        "sub_scores": sub_scores,
        "commentary": quality["commentary"],
        "signals": {
            "has_readme": deterministic["has_readme"],
            "has_tests": deterministic["has_tests"],
            "has_ci": deterministic["has_ci"],
            "has_license": deterministic["has_license"],
        },
    }
