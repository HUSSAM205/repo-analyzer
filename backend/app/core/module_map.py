"""Deterministic module/directory structure diagram -- zero LLM tokens.

Distinct from flow_map.py's AI-generated request-flow diagram (which infers
*behavior* -- how a request moves through the system -- and can hallucinate
that story on a repo the model can't fully reason about): this one only
ever describes structure that is directly, mechanically observable from
file paths -- the top-level directory layout and how many files live in
each -- so it's always available and always accurate, at the cost of not
explaining what any of it *does*.
"""

from app.db.models import File

_MAX_TOP_LEVEL_NODES = 18
# Directories that are real on disk but never meaningful architecture --
# including them would just be noise (or, for vendored/build dirs, could
# dominate the file count and crowd out every real module).
_SKIP_DIRS = {
    "node_modules", ".git", ".next", "dist", "build", "__pycache__",
    ".venv", "venv", ".pytest_cache", "coverage", ".turbo",
}


def _mermaid_escape(label: str) -> str:
    return label.replace('"', "'")


def _top_level_dir(path: str) -> str | None:
    normalized = path.replace("\\", "/").lstrip("/")
    if "/" not in normalized:
        return None
    top = normalized.split("/", 1)[0]
    return None if top in _SKIP_DIRS else top


def _directory_counts(files: list[File]) -> tuple[dict[str, int], int]:
    counts: dict[str, int] = {}
    root_file_count = 0
    for f in files:
        top = _top_level_dir(f.path)
        if top is None:
            root_file_count += 1
        else:
            counts[top] = counts.get(top, 0) + 1
    return counts, root_file_count


def directory_breakdown(files: list[File]) -> dict[str, int]:
    """Top-level directory -> file count, the same raw breakdown
    build_module_map renders as a Mermaid diagram -- exposed separately for
    callers (e.g. repo_diff.py's side-by-side comparison) that need the raw
    counts rather than a diagram string."""
    counts, _ = _directory_counts(files)
    return counts


def build_module_map(files: list[File]) -> dict:
    """Fully deterministic -- always succeeds (an empty/flat repo just
    yields a diagram with only a root node, still valid Mermaid)."""
    counts, root_file_count = _directory_counts(files)

    # Most-populated directories first -- with a real repo's file count,
    # a long tail of single-file directories is rarely worth a node each;
    # capping keeps the diagram readable rather than an illegible wall of
    # boxes for a large repo.
    top_dirs = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    shown = top_dirs[:_MAX_TOP_LEVEL_NODES]
    omitted_count = len(top_dirs) - len(shown)

    lines = ["flowchart TD", '  ROOT["repo root"]']
    for i, (name, count) in enumerate(shown):
        node_id = f"D{i}"
        label = _mermaid_escape(f"{name}/ ({count} file{'s' if count != 1 else ''})")
        lines.append(f'  {node_id}["{label}"]')
        lines.append(f"  ROOT --> {node_id}")
    if root_file_count:
        lines.append(f'  ROOTFILES(["{root_file_count} file{"s" if root_file_count != 1 else ""} at root"])')
        lines.append("  ROOT --> ROOTFILES")
    if omitted_count:
        lines.append(f'  MORE(["+ {omitted_count} more director{"y" if omitted_count == 1 else "ies"}"])')
        lines.append("  ROOT --> MORE")

    return {
        "diagram": "\n".join(lines),
        "directory_count": len(top_dirs),
        "file_count": len(files),
    }
