import logging

from app.core.llm import LLMClient, Message
from app.core.token_budget import MAX_CONTEXT_CHARS, sanitize_context
from app.db.models import File

logger = logging.getLogger(__name__)

# Same reasoning as domain_briefing.py/code_annotation.py: a hard character
# budget per sampled file, plus an overall prompt budget, keeps this well
# clear of Groq's per-minute token limits regardless of repo size.
_MAX_SAMPLE_FILES = 12
_MAX_FILE_CHARS = 3000
_MAX_TREE_PATHS = 300

_MANIFEST_NAMES = {
    "package.json", "pyproject.toml", "requirements.txt", "Pipfile",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "Makefile",
    "go.mod", "Cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts", "composer.json",
}

_SYSTEM_PROMPT = (
    "You are generating a high-quality README.md for a code repository, to "
    "hand a new contributor everything they need to get started. Respond "
    "with the README's raw Markdown content only -- no code fence wrapping "
    "the whole document, no commentary before or after. Structure it with "
    "clear headings: a one-paragraph project summary, a Features/Overview "
    "section (if you can tell what the project does from the code), a Tech "
    "Stack section, an Installation section with concrete, runnable "
    "commands you can infer from the manifest files/scripts you're shown "
    "(package.json scripts, requirements.txt, Dockerfile, etc.), a Usage "
    "section, and a Project Structure section briefly describing the main "
    "directories. Do not invent details you cannot infer from what's "
    "provided -- prefer a shorter, accurate section over a longer "
    "speculative one."
)


def _find_existing_readme(files: list[File]) -> str | None:
    for f in files:
        if "/" not in f.path and f.path.lower().startswith("readme"):
            return f.content
    return None


def _pick_sample_files(files: list[File]) -> list[File]:
    # Manifests/config first (the cheapest, most reliable signal for real
    # install/run commands), then whatever source files are left.
    priority = [f for f in files if f.path.rsplit("/", 1)[-1] in _MANIFEST_NAMES]
    priority_paths = {f.path for f in priority}
    rest = [f for f in files if f.path not in priority_paths]
    return (priority + rest)[:_MAX_SAMPLE_FILES]


def _build_prompt(files: list[File], domain_briefing: dict | None, existing_readme: str | None) -> str:
    parts: list[str] = []
    if domain_briefing:
        parts.append("Known project classification (from prior analysis):")
        parts.append(f"- Domain: {domain_briefing.get('primary_field', 'Unknown')}")
        parts.append(f"- Audience: {domain_briefing.get('target_audience', 'Unknown')}")
        badges = domain_briefing.get("tech_stack_badges") or []
        if badges:
            parts.append(f"- Detected tech stack: {', '.join(badges)}")
        parts.append("")
    if existing_readme:
        parts.append("Existing README (may be outdated/incomplete -- treat as a starting point, not ground truth):")
        parts.append(sanitize_context(existing_readme[:2000]))
        parts.append("")

    paths = sorted(f.path for f in files)
    tree_lines = paths[:_MAX_TREE_PATHS]
    if len(paths) > _MAX_TREE_PATHS:
        tree_lines.append(f"... and {len(paths) - _MAX_TREE_PATHS} more files")
    parts.append("File tree:")
    parts.append("\n".join(tree_lines))
    parts.append("")

    parts.append("Sampled file contents:")
    budget = MAX_CONTEXT_CHARS
    for f in _pick_sample_files(files):
        snippet = sanitize_context(f.content[:_MAX_FILE_CHARS])
        block = f"--- {f.path} ---\n{snippet}\n"
        if len(block) > budget:
            break
        parts.append(block)
        budget -= len(block)

    return "\n".join(parts)


def build_deterministic_readme(files: list[File], domain_briefing: dict | None) -> str:
    """A best-effort README -- no LLM call, so it's always available. Used
    as the fallback when generate_readme's real, AI-written draft can't be
    produced (provider exhausted/erroring), so a viewer always gets a real
    document instead of a 503.

    If the repo already has a real, human-authored README, that's already
    a better answer than anything this function could synthesize -- return
    it as-is (only labeled as a passthrough) rather than replacing it with
    a lesser generated one. Only genuinely builds one from scratch (file
    tree + domain_briefing, both already known with no LLM call) when
    there's no existing README to fall back to.
    """
    existing_readme = _find_existing_readme(files)
    if existing_readme:
        return (
            "> AI-generated documentation is temporarily unavailable -- showing this "
            "repository's own existing README instead.\n\n" + existing_readme
        )

    lines = ["# " + (domain_briefing.get("primary_field") if domain_briefing else None or "Repository Overview")]
    lines.append(
        "\n_AI-generated documentation is temporarily unavailable, so this is a minimal "
        "auto-generated summary from the repository's file structure -- refresh later for a full "
        "AI-written README._\n"
    )
    if domain_briefing:
        audience = domain_briefing.get("target_audience")
        if audience:
            lines.append(f"**Built for:** {audience}\n")
        overview = domain_briefing.get("architecture_overview")
        if overview:
            lines.append(f"## Overview\n\n{overview}\n")
        badges = domain_briefing.get("tech_stack_badges") or []
        if badges:
            lines.append(f"## Tech Stack\n\n{', '.join(badges)}\n")

    lines.append("## Project Structure\n")
    paths = sorted(f.path for f in files)[:_MAX_TREE_PATHS]
    lines.append("```\n" + "\n".join(paths) + "\n```\n")
    return "\n".join(lines)


async def generate_readme(files: list[File], domain_briefing: dict | None, llm_client: LLMClient) -> str | None:
    """Generates a README.md draft for the repo from its already-ingested
    files (see app/db/models.py's File) and, if present, its
    domain_briefing.

    Returns None on any failure (LLM error, transport error, empty
    response) rather than raising -- the caller (see
    app/api/routes/repos.py's get_readme) treats None as "temporarily
    unavailable" and does not cache it, so a later request can retry once
    the provider recovers. Never caches a failure.
    """
    if not files:
        return None

    existing_readme = _find_existing_readme(files)
    prompt = _build_prompt(files, domain_briefing, existing_readme)

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

        text = accumulated.strip()
        if not text:
            raise ValueError("LLM returned an empty README")
        return text
    except Exception:
        logger.warning("README generation failed", exc_info=True)
        return None
