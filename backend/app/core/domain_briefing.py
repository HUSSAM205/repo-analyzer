import json
import logging
from collections import Counter
from collections.abc import Sequence

from app.core.chunker import Chunk
from app.core.ingestion import WalkedFile, WalkResult
from app.core.llm import LLMClient, Message

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Deterministic file-type distribution
# ---------------------------------------------------------------------------

# Extension -> human-readable group label. Extensions not listed here fall
# back to a generic "<EXT> files" label (see _file_type_distribution), so
# this only needs to cover the groupings that deserve a nicer/merged name.
_EXTENSION_GROUPS: dict[str, str] = {
    ".py": "Python backend files",
    ".ts": "TypeScript/React files",
    ".tsx": "TypeScript/React files",
    ".js": "JavaScript files",
    ".jsx": "JavaScript files",
    ".go": "Go files",
    ".java": "Java files",
    ".md": "Documentation files",
    ".mdx": "Documentation files",
    ".rst": "Documentation files",
    ".yml": "Config files",
    ".yaml": "Config files",
    ".toml": "Config files",
    ".ini": "Config files",
    ".cfg": "Config files",
    ".json": "JSON/config files",
    ".html": "HTML files",
    ".htm": "HTML files",
    ".css": "Stylesheets",
    ".scss": "Stylesheets",
    ".sass": "Stylesheets",
    ".less": "Stylesheets",
    ".rb": "Ruby files",
    ".rs": "Rust files",
    ".c": "C/C++ files",
    ".h": "C/C++ files",
    ".cpp": "C/C++ files",
    ".cc": "C/C++ files",
    ".hpp": "C/C++ files",
    ".php": "PHP files",
    ".sql": "SQL files",
    ".sh": "Shell scripts",
    ".bash": "Shell scripts",
    ".ps1": "Shell scripts",
    ".xml": "XML files",
    ".txt": "Text files",
    ".cs": ".NET files",
    ".kt": "Kotlin files",
    ".swift": "Swift files",
}

_TOP_N_FILE_TYPES = 6

# ---------------------------------------------------------------------------
# Deterministic tech-stack badge detection (exact filename match)
# ---------------------------------------------------------------------------

_MANIFEST_BADGES: dict[str, str] = {
    "package.json": "Node.js",
    "requirements.txt": "Python",
    "pyproject.toml": "Python",
    "Pipfile": "Python",
    "Dockerfile": "Docker",
    "docker-compose.yml": "Docker",
    "docker-compose.yaml": "Docker",
    "go.mod": "Go",
    "Cargo.toml": "Rust",
    "pom.xml": "Java",
    "build.gradle": "Java",
    "build.gradle.kts": "Java",
    "tsconfig.json": "TypeScript",
    "Gemfile": "Ruby",
    "composer.json": "PHP",
    "next.config.js": "Next.js",
    "next.config.mjs": "Next.js",
    "vite.config.ts": "Vite",
    "vite.config.js": "Vite",
}

_MAX_TECH_BADGES = 8
_MAX_LLM_BADGES = 3
_MAX_TREE_PATHS = 200
_MAX_SYMBOL_SAMPLES = 30
_README_MAX_CHARS = 2000

_SYSTEM_PROMPT = (
    "You are analyzing a code repository to produce a short structured "
    "briefing for a product pitch (\"paste any GitHub link and get an "
    "instant architectural briefing\"). Respond with strict JSON only -- "
    "no markdown code fences, no commentary, no text before or after the "
    "JSON object. The JSON object must have exactly these keys: "
    "\"primary_field\" (a short label for the repo's domain, e.g. "
    "\"Full-Stack Web SaaS\" or \"Computer Vision & Edge AI\"), "
    "\"target_audience\" (a short phrase describing who this repo is built "
    "for or useful to, e.g. \"Backend engineers building async job "
    "pipelines\"), \"architecture_overview\" (2-4 sentences describing how "
    "data flows through the repo), and \"tech_stack_badges\" (a JSON array "
    "of up to 3 short framework/library names you recognize from the code "
    "that are not already listed in the provided tech stack markers -- "
    "return an empty array if you have nothing to add)."
)

_FALLBACK_BRIEFING = {
    "primary_field": "Unclassified",
    "target_audience": "General developers",
    "architecture_overview": "Automatic classification is currently unavailable for this repository.",
}


def _extension(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


def _file_type_distribution(files: Sequence[WalkedFile]) -> list[dict]:
    counts: Counter[str] = Counter()
    for f in files:
        ext = _extension(f.path)
        if ext in _EXTENSION_GROUPS:
            label = _EXTENSION_GROUPS[ext]
        elif ext:
            label = f"{ext.lstrip('.').upper()} files"
        else:
            label = "Other files"
        counts[label] += 1

    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:_TOP_N_FILE_TYPES]
    return [{"label": label, "count": count} for label, count in ranked]


def _deterministic_tech_badges(files: Sequence[WalkedFile]) -> list[str]:
    present_names = {f.path.rsplit("/", 1)[-1] for f in files}

    badges: list[str] = []
    for filename, badge in _MANIFEST_BADGES.items():
        if filename in present_names and badge not in badges:
            badges.append(badge)

    if ".NET" not in badges and any(name.endswith(".csproj") for name in present_names):
        badges.append(".NET")

    return badges


def _find_readme(files: Sequence[WalkedFile]) -> str | None:
    for f in files:
        if "/" not in f.path and f.path.lower().startswith("readme"):
            return f.content[:_README_MAX_CHARS]
    return None


def _file_tree_sample(files: Sequence[WalkedFile]) -> str:
    paths = sorted(f.path for f in files)
    if len(paths) <= _MAX_TREE_PATHS:
        lines = paths
    else:
        lines = paths[:_MAX_TREE_PATHS] + [f"... and {len(paths) - _MAX_TREE_PATHS} more files"]
    return "\n".join(lines) if lines else "(no files)"


def _symbol_samples(chunks: Sequence[Chunk]) -> str:
    samples: list[str] = []
    for chunk in chunks:
        if chunk.symbol_name:
            samples.append(f"{chunk.file_path}: {chunk.symbol_name} ({chunk.node_type})")
        if len(samples) >= _MAX_SYMBOL_SAMPLES:
            break
    return "\n".join(samples) if samples else "(none)"


def _build_prompt(walk_result: WalkResult, deterministic_badges: list[str]) -> str:
    readme = _find_readme(walk_result.files)
    parts = [
        f"File tree ({len(walk_result.files)} files processed):",
        _file_tree_sample(walk_result.files),
        "",
        f"Deterministically detected tech stack markers: {', '.join(deterministic_badges) or '(none detected)'}",
        "",
        "Representative code symbols found (file: symbol (kind)):",
        _symbol_samples(walk_result.chunks),
    ]
    if readme:
        parts += ["", "README contents (truncated):", readme]
    return "\n".join(parts)


def _parse_llm_json(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        # Models sometimes wrap "strict JSON only" output in a markdown
        # fence anyway. Strip the opening fence (with optional language
        # tag, e.g. "```json") and the closing fence.
        stripped = stripped[3:]
        if stripped[:4].lower() == "json":
            stripped = stripped[4:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()

    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("LLM response was not a JSON object")
    for key in ("primary_field", "target_audience", "architecture_overview"):
        if key not in parsed:
            raise ValueError(f"LLM response missing required key: {key}")
    return parsed


async def generate_domain_briefing(walk_result: WalkResult, llm_client: LLMClient) -> dict:
    """Produce the "Domain & Purpose Classification" briefing for a repo.

    `file_type_distribution` and the manifest-based portion of
    `tech_stack_badges` are computed deterministically from `walk_result`
    and never depend on the LLM call succeeding. `primary_field`,
    `target_audience`, `architecture_overview`, and up to a few additional
    `tech_stack_badges` come from a single LLM call. If that call fails for
    any reason (network error, empty/invalid key, malformed JSON response),
    this function never raises -- it logs a warning and falls back to a
    generic qualitative briefing while still returning the deterministic
    parts.
    """
    file_type_distribution = _file_type_distribution(walk_result.files)
    deterministic_badges = _deterministic_tech_badges(walk_result.files)

    try:
        prompt = _build_prompt(walk_result, deterministic_badges)
        messages = [Message(role="user", content=prompt)]

        accumulated = ""
        llm_error: str | None = None
        async for event in llm_client.stream_chat(messages, tools=[], system_prompt=_SYSTEM_PROMPT):
            if event.type == "token":
                accumulated += event.token or ""
            elif event.type == "error":
                llm_error = event.error

        if llm_error is not None:
            raise RuntimeError(f"LLM provider returned an error: {llm_error}")

        parsed = _parse_llm_json(accumulated)

        merged_badges = list(deterministic_badges)
        llm_badges = parsed.get("tech_stack_badges") or []
        if isinstance(llm_badges, list):
            for badge in llm_badges[:_MAX_LLM_BADGES]:
                if isinstance(badge, str) and badge and badge not in merged_badges:
                    merged_badges.append(badge)
                if len(merged_badges) >= _MAX_TECH_BADGES:
                    break

        return {
            "primary_field": str(parsed["primary_field"]),
            "target_audience": str(parsed["target_audience"]),
            "architecture_overview": str(parsed["architecture_overview"]),
            "tech_stack_badges": merged_badges[:_MAX_TECH_BADGES],
            "file_type_distribution": file_type_distribution,
        }
    except Exception:
        logger.warning(
            "Domain briefing LLM classification failed; falling back to generic briefing", exc_info=True
        )
        return {
            **_FALLBACK_BRIEFING,
            "tech_stack_badges": deterministic_badges[:_MAX_TECH_BADGES],
            "file_type_distribution": file_type_distribution,
        }
