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
    "instant architectural briefing\"), PLUS a beginner-friendly \"Explain "
    "Like I'm 5\" onboarding guide for someone new to this codebase (and "
    "possibly new to programming). Respond with strict JSON only -- no "
    "markdown code fences, no commentary, no text before or after the JSON "
    "object. The JSON object must have exactly these keys:\n"
    "\"primary_field\" (a short label for the repo's domain, e.g. "
    "\"Full-Stack Web SaaS\" or \"Computer Vision & Edge AI\"),\n"
    "\"target_audience\" (a short phrase describing who this repo is built "
    "for or useful to, e.g. \"Backend engineers building async job "
    "pipelines\"),\n"
    "\"architecture_overview\" (2-4 sentences describing how data flows "
    "through the repo, written for an experienced engineer),\n"
    "\"tech_stack_badges\" (a JSON array of up to 3 short framework/library "
    "names you recognize from the code that are not already listed in the "
    "provided tech stack markers -- return an empty array if you have "
    "nothing to add),\n"
    "\"beginner_summary\" (2-3 sentences answering \"what is this project?\" "
    "for a total beginner, using a plain-language, everyday analogy -- e.g. "
    "\"Think of this like a restaurant: the frontend is the dining room "
    "where customers place orders, and the backend is the kitchen that "
    "actually prepares them.\"),\n"
    "\"tech_stack_explained\" (a JSON array of objects, one per major "
    "technology actually used in this repo -- merge/cover the same "
    "technologies as tech_stack_badges plus the deterministically detected "
    "markers you were given, do not invent unused ones -- each object has "
    "\"name\" (the technology's name) and \"role\" (one short plain-English "
    "sentence explaining its JOB in this project using a role metaphor, e.g. "
    "\"React = builds what you see and click on (the user interface)\" or "
    "\"FastAPI = the brain/server that receives requests and decides what to "
    "do\" or \"PostgreSQL = the filing cabinet that remembers everything "
    "between visits\"). Cap at 6 entries, most important first.\n"
    "\"learning_path\" (a JSON array of 3-6 objects describing a step-by-step "
    "reading order for a beginner exploring this specific repo for the "
    "first time -- each object has \"file_or_topic\" (an actual file path "
    "from the provided file tree, or a short topic name if no single file "
    "fits) and \"why\" (one short sentence on what they'll learn there and "
    "why that's a good next step). Order from \"absolute first thing to "
    "open\" to \"go here once you're comfortable\".\n"
    "\"key_takeaways\" (a JSON array of 3-5 short strings -- concrete "
    "patterns, conventions, or best practices YOU CAN ACTUALLY SEE in this "
    "specific codebase that a beginner could learn from and reuse in their "
    "own projects -- not generic programming advice)."
)

_FALLBACK_BRIEFING = {
    "primary_field": "Unclassified",
    "target_audience": "General developers",
    "architecture_overview": "Automatic classification is currently unavailable for this repository.",
    "beginner_summary": "A beginner-friendly summary isn't available for this repository right now.",
    "tech_stack_explained": [],
    "learning_path": [],
    "key_takeaways": [],
}

# ---------------------------------------------------------------------------
# Deterministic classification -- used when the LLM call fails. Unlike the
# flagship tools (readme, flow-map, etc), which lazily generate-on-request
# and can simply be retried on the next visit, this briefing is generated
# ONCE, synchronously, during analysis itself, and cached permanently with
# no automatic retry -- an LLM failure at exactly that moment used to mean
# "Unclassified" forever for that repo. This infers a real category and a
# templated analogy from cheap, already-computed signals (manifest-based
# tech badges, plus a scan of manifest file *contents* for AI/ML and
# DevOps/IaC library names those badges alone don't capture) instead.
# ---------------------------------------------------------------------------

_AI_ML_LIBRARY_HINTS = (
    "tensorflow", "torch", "pytorch", "scikit-learn", "scikit_learn", "keras",
    "transformers", "xgboost", "lightgbm", "jax", "openai", "anthropic",
    "langchain", "langgraph", "sentence-transformers", "diffusers",
)
_DEVOPS_HINTS = ("terraform", "ansible", "kubernetes", "helm", "pulumi", "kubectl")
_FRONTEND_HINTS = ("react", "vue", "angular", "svelte", "next", "nuxt")
_BACKEND_BADGES = {"Python", "Node.js", "Go", "Java", ".NET", "Ruby", "PHP", "Rust"}
_MANIFEST_FILENAMES_FOR_CONTENT_SCAN = {
    "requirements.txt", "package.json", "pyproject.toml", "Pipfile", "Cargo.toml", "go.mod",
}
_MANIFEST_SCAN_CHAR_LIMIT = 20_000

_FIELD_ANALOGIES: dict[str, str] = {
    "AI / Machine Learning": (
        "Think of this like a apprentice that gets better at a task by studying lots of examples, "
        "rather than being told the exact rules up front."
    ),
    "DevOps / Infrastructure": (
        "Think of this like the blueprints and the automated construction crew for a building, rather "
        "than the building's furniture -- it's about reliably setting up and running everything else."
    ),
    "Full-Stack Web Application": (
        "Think of this like a restaurant: the frontend is the dining room where visitors place orders, "
        "and the backend is the kitchen that actually prepares them."
    ),
    "Frontend Web Application": (
        "Think of this like the storefront and shop window of a business -- what a visitor actually "
        "sees and clicks on in their browser."
    ),
    "Backend Web API / Service": (
        "Think of this like a kitchen with no dining room -- it doesn't have its own visible interface, "
        "it just receives orders (requests) and sends back what was asked for."
    ),
    "Software Library / Tool": (
        "Think of this like a toolbox someone else's project can reach into, rather than a finished "
        "product on its own."
    ),
}


def _manifest_content_sample(files: Sequence[WalkedFile]) -> str:
    parts = [
        f.content for f in files
        if f.path.rsplit("/", 1)[-1] in _MANIFEST_FILENAMES_FOR_CONTENT_SCAN
    ]
    return "\n".join(parts)[:_MANIFEST_SCAN_CHAR_LIMIT].lower()


def _has_devops_signal(files: Sequence[WalkedFile]) -> bool:
    # DevOps/IaC repos are identified by file EXTENSION/PATH far more
    # reliably than by any manifest's content -- a Terraform repo's actual
    # infrastructure lives in *.tf files, an Ansible repo in playbooks/
    # roles directories, neither of which is a "manifest" in the
    # dependency-file sense _manifest_content_sample scans.
    for f in files:
        lowered = f.path.lower()
        if lowered.endswith(".tf") or lowered.endswith(".tfvars"):
            return True
        if any(hint in lowered for hint in _DEVOPS_HINTS):
            return True
    return False


def _infer_primary_field(files: Sequence[WalkedFile], deterministic_badges: list[str]) -> str:
    manifest_text = _manifest_content_sample(files)

    if any(hint in manifest_text for hint in _AI_ML_LIBRARY_HINTS):
        return "AI / Machine Learning"
    if _has_devops_signal(files):
        return "DevOps / Infrastructure"

    has_frontend = any(hint in manifest_text for hint in _FRONTEND_HINTS) or "Next.js" in deterministic_badges
    has_backend = any(badge in _BACKEND_BADGES for badge in deterministic_badges)
    if has_frontend and has_backend:
        return "Full-Stack Web Application"
    if has_frontend:
        return "Frontend Web Application"
    if has_backend:
        return "Backend Web API / Service"
    return "Software Library / Tool"


def _deterministic_classification(files: Sequence[WalkedFile], deterministic_badges: list[str]) -> dict:
    primary_field = _infer_primary_field(files, deterministic_badges)
    return {
        "primary_field": primary_field,
        "target_audience": "Developers working with this project's tech stack",
        "architecture_overview": (
            f"AI-based classification is temporarily unavailable, so this category ({primary_field}) was "
            "inferred from the repository's manifest files and detected tech stack rather than a full "
            "reading of the code."
        ),
        "beginner_summary": _FIELD_ANALOGIES.get(
            primary_field,
            "AI-based classification is temporarily unavailable, so a tailored beginner explanation "
            "isn't ready yet for this repository.",
        ),
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


_MAX_TECH_STACK_EXPLAINED = 6
_MAX_LEARNING_PATH_STEPS = 6
_MAX_KEY_TAKEAWAYS = 5


def _extract_tech_stack_explained(parsed: dict) -> list[dict]:
    # Lenient by design, same reasoning as _parse_summary_json in
    # code_annotation.py: a malformed or missing entry just means this one
    # beginner-facing field falls back to an empty list, not that the whole
    # briefing (including the always-required primary_field/etc above)
    # fails and falls back to the generic placeholder.
    raw = parsed.get("tech_stack_explained")
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw[:_MAX_TECH_STACK_EXPLAINED]:
        if isinstance(item, dict) and item.get("name") and item.get("role"):
            result.append({"name": str(item["name"]), "role": str(item["role"])})
    return result


def _extract_learning_path(parsed: dict) -> list[dict]:
    raw = parsed.get("learning_path")
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw[:_MAX_LEARNING_PATH_STEPS]:
        if isinstance(item, dict) and item.get("file_or_topic") and item.get("why"):
            result.append({"file_or_topic": str(item["file_or_topic"]), "why": str(item["why"])})
    return result


def _extract_key_takeaways(parsed: dict) -> list[str]:
    raw = parsed.get("key_takeaways")
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw[:_MAX_KEY_TAKEAWAYS] if isinstance(item, str) and item]


async def generate_domain_briefing(walk_result: WalkResult, llm_client: LLMClient) -> dict:
    """Produce the "Domain & Purpose Classification" briefing for a repo,
    plus a beginner-facing "onboarding guide" (beginner_summary,
    tech_stack_explained, learning_path, key_takeaways) from the same call.

    `file_type_distribution` and the manifest-based portion of
    `tech_stack_badges` are computed deterministically from `walk_result`
    and never depend on the LLM call succeeding. Every other field comes
    from a single LLM call -- one call produces both the professional
    briefing and the beginner guide together, rather than two separate LLM
    round-trips, to keep analysis latency the same as before this feature
    was added. If that call fails for any reason (network error, empty/
    invalid key, malformed JSON response), this function never raises -- it
    logs a warning and falls back to a generic placeholder for every LLM-
    derived field while still returning the deterministic parts. A field
    the model omits or returns malformed (e.g. `learning_path` present but
    `tech_stack_explained` missing) degrades that one field to an empty
    list/fallback string rather than failing the whole briefing -- the
    three original fields (primary_field/target_audience/
    architecture_overview) remain the only ones whose absence triggers the
    full generic fallback (see _parse_llm_json).
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
            "beginner_summary": str(parsed.get("beginner_summary") or _FALLBACK_BRIEFING["beginner_summary"]),
            "tech_stack_explained": _extract_tech_stack_explained(parsed),
            "learning_path": _extract_learning_path(parsed),
            "key_takeaways": _extract_key_takeaways(parsed),
        }
    except Exception:
        logger.warning(
            "Domain briefing LLM classification failed; falling back to deterministic classification",
            exc_info=True,
        )
        return {
            **_FALLBACK_BRIEFING,
            **_deterministic_classification(walk_result.files, deterministic_badges),
            "tech_stack_badges": deterministic_badges[:_MAX_TECH_BADGES],
            "file_type_distribution": file_type_distribution,
        }
