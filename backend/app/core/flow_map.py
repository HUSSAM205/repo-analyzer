import logging

from app.core.llm import LLMClient, Message
from app.core.token_budget import MAX_CONTEXT_CHARS, sanitize_context
from app.db.models import File

logger = logging.getLogger(__name__)

_MAX_TREE_PATHS = 200
_MAX_SAMPLE_FILES = 8
_MAX_FILE_CHARS = 1800

# Filenames/paths that usually carry the actual request-handling wiring of a
# web app -- sampled preferentially so the diagram is grounded in real
# routing/controller/service code rather than the file tree alone.
_LAYER_HINTS = (
    "route", "router", "controller", "handler", "endpoint", "api",
    "service", "usecase", "use_case", "repository", "model", "schema",
    "view", "middleware",
)

_SKIP_SUFFIXES = (
    ".lock", ".min.js", ".min.css", ".map", ".svg", ".png", ".jpg", ".jpeg",
    ".gif", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".pdf", ".zip",
)
_SKIP_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "uv.lock", "poetry.lock"}

_SYSTEM_PROMPT = (
    "You are producing a visual architecture / request-flow diagram for a code "
    "repository, in Mermaid.js flowchart syntax. Base it only on the file tree "
    "and sampled file contents you were given -- use real file/module names "
    "from the repo wherever you can identify them, rather than generic "
    "placeholder labels. Respond with ONLY raw Mermaid syntax -- no markdown "
    "code fences, no commentary, no text before or after it. The first line "
    "must be exactly `flowchart TD`. Model the actual request-handling path "
    "you can infer (e.g. entry point/router -> controller/handler -> "
    "service/business-logic layer -> data layer/database, or whatever layers "
    "this specific repo actually has -- skip a layer if the repo genuinely "
    "doesn't have one, and add a client/user node at the top if relevant). "
    "Use 6-14 nodes total. Use Mermaid's `-->` for a normal call/dependency "
    "edge and `-.->` for an async/event-based one where relevant. Keep node "
    "labels short (a file, module, or component name, optionally with a 2-4 "
    "word description in parentheses)."
)


def _is_scannable(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if name in _SKIP_NAMES:
        return False
    return not path.lower().endswith(_SKIP_SUFFIXES)


def _layer_score(path: str) -> int:
    lowered = path.lower()
    return sum(1 for hint in _LAYER_HINTS if hint in lowered)


def _pick_sample_files(files: list[File]) -> list[File]:
    scannable = [f for f in files if _is_scannable(f.path)]
    # Layer-relevant files first (routes/controllers/services/models/etc,
    # most-relevant-looking first), then fall back to filling any remaining
    # slots with whatever else is available -- so a repo with no filenames
    # matching the hints still gets a reasonable, non-empty sample.
    ranked = sorted(scannable, key=lambda f: (-_layer_score(f.path), f.path))
    return ranked[:_MAX_SAMPLE_FILES]


def _file_tree_sample(files: list[File]) -> str:
    paths = sorted(f.path for f in files)
    if len(paths) <= _MAX_TREE_PATHS:
        lines = paths
    else:
        lines = paths[:_MAX_TREE_PATHS] + [f"... and {len(paths) - _MAX_TREE_PATHS} more files"]
    return "\n".join(lines) if lines else "(no files)"


def _build_prompt(files: list[File]) -> str:
    parts = ["Repository file tree:", _file_tree_sample(files), "", "Sampled file contents:"]
    budget = MAX_CONTEXT_CHARS
    for f in _pick_sample_files(files):
        snippet = sanitize_context(f.content[:_MAX_FILE_CHARS])
        block = f"--- {f.path} ---\n{snippet}\n"
        if len(block) > budget:
            break
        parts.append(block)
        budget -= len(block)
    return "\n".join(parts)


def _clean_diagram(text: str) -> str | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped[3:]
        if stripped[:7].lower() == "mermaid":
            stripped = stripped[7:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()

    # Cheap sanity check rather than a real Mermaid parser: confirm this at
    # least starts with a recognized diagram-type keyword so a badly broken
    # response (e.g. the model apologizing in prose instead of complying)
    # never gets cached as a "diagram" the frontend then fails to render.
    first_line = stripped.splitlines()[0].strip().lower() if stripped else ""
    if not (first_line.startswith("flowchart") or first_line.startswith("graph")):
        return None
    return stripped


# Layer, in the order a request typically flows through one -- used only
# by the deterministic fallback below, distinct from _LAYER_HINTS (which
# scores *individual files* for prompt sampling). Each entry's hints are
# checked against every file path; the first repo-wide match for a layer
# is enough to include that layer's node in the fallback diagram.
_DETERMINISTIC_LAYERS: list[tuple[tuple[str, ...], str]] = [
    (("route", "router", "api/", "endpoint", "handler", "controller"), "Routes / Controllers"),
    (("service", "usecase", "use_case", "business"), "Services / Business Logic"),
    (("repository", "model", "schema", "entity", "dao"), "Models / Data Layer"),
]
_DETERMINISTIC_DB_HINTS = ("model", "schema", "entity", "repository", "migrations", "prisma", "sql")


def build_deterministic_flow_map(files: list[File]) -> str:
    """A best-effort Mermaid flowchart built purely from directory-name
    heuristics -- no LLM call, so it's always available. Used as the
    fallback when generate_flow_map's real, code-grounded diagram can't be
    produced (provider exhausted/erroring), so a viewer gets a genuinely
    useful (if generic) diagram instead of a 503. Never fails: even a repo
    matching none of the heuristics still gets a minimal, valid diagram.
    """
    paths_lower = [f.path.lower() for f in files]

    nodes = ["Client"]
    for hints, label in _DETERMINISTIC_LAYERS:
        if any(hint in p for p in paths_lower for hint in hints):
            nodes.append(label)
    if len(nodes) == 1:
        # No recognizable layer at all -- still produce a valid, if
        # minimal, diagram rather than an empty/single-node one.
        nodes.append("Application")
    if any(hint in p for p in paths_lower for hint in _DETERMINISTIC_DB_HINTS):
        nodes.append("Database")

    ids = [f"N{i}" for i in range(len(nodes))]
    lines = ["flowchart TD"]
    lines.extend(f'  {ids[i]}["{label}"]' for i, label in enumerate(nodes))
    lines.extend(f"  {ids[i]} --> {ids[i + 1]}" for i in range(len(nodes) - 1))
    return "\n".join(lines)


async def generate_flow_map(files: list[File], llm_client: LLMClient) -> str | None:
    """Generates a Mermaid flowchart describing this repo's request-handling
    architecture. Returns None on any failure (never raises) so the caller
    does not cache a broken result.
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

        return _clean_diagram(accumulated)
    except Exception:
        logger.warning("Flow-map generation failed", exc_info=True)
        return None
