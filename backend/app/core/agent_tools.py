from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.embeddings import embed_text
from app.core.llm import ToolSpec
from app.core.search import hybrid_search
from app.core.token_budget import MAX_CONTEXT_TOKENS, truncate_to_token_budget
from app.db.models import File

SEARCH_CODE_TOOL_SPEC = ToolSpec(
    name="search_code",
    description=(
        "Search the repository's code for content relevant to a natural-language "
        "query. Returns ranked code chunks with file path, symbol name, and line "
        "range. Best for finding code related to a topic or keyword when you "
        "don't already know which file it's in."
    ),
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string", "description": "What to search for"}},
        "required": ["query"],
    },
)

LIST_DIRECTORY_TOOL_SPEC = ToolSpec(
    name="list_directory",
    description=(
        "List the files and subdirectories directly inside a directory of this "
        "repository (not recursive -- subdirectories are shown but not expanded). "
        "Pass an empty string for the repository root. Use this first for broad "
        "questions like 'explain the architecture' to see the overall layout "
        "before deciding what to read or search for."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path relative to the repo root, or empty string for the root",
            }
        },
        "required": [],
    },
)

READ_FILE_TOOL_SPEC = ToolSpec(
    name="read_file",
    description=(
        "Read the full contents of one specific file in this repository, given "
        "its exact path (as seen in search_code results or list_directory "
        "output). Use this when you need the complete picture of a file -- e.g. "
        "a config/manifest file, or a source file where a chunked search_code "
        "snippet isn't enough context."
    ),
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Exact file path relative to the repo root"}},
        "required": ["path"],
    },
)


async def search_code(db: AsyncSession, repo_id: UUID, query: str, limit: int = 5) -> str:
    query_embedding = await run_in_threadpool(embed_text, query)
    results = await hybrid_search(db, repo_id, query_text=query, query_embedding=query_embedding, limit=limit)
    if not results:
        return "No matching code found for this query."

    blocks = []
    for r in results:
        symbol = f" ({r.symbol_name})" if r.symbol_name else ""
        blocks.append(f"### {r.file_path}:{r.start_line}-{r.end_line}{symbol}\n```\n{r.content}\n```")
    # Several chunks concatenated (up to `limit`) can add up well past a
    # single tool result's fair share of a request's token budget -- see
    # token_budget.py for why this cap exists (a 413 "tokens per minute"
    # failure this was added to prevent).
    return truncate_to_token_budget("\n\n".join(blocks), MAX_CONTEXT_TOKENS)


async def list_directory(db: AsyncSession, repo_id: UUID, path: str = "") -> str:
    result = await db.execute(select(File.path).where(File.repo_id == repo_id))
    all_paths = result.scalars().all()

    normalized = path.strip("/")
    prefix = f"{normalized}/" if normalized else ""

    # name -> whether it's a directory (any matching path has more path
    # segments after it) vs a file (a path ends exactly there).
    entries: dict[str, bool] = {}
    prefix_matched = False
    for p in all_paths:
        if not p.startswith(prefix):
            continue
        prefix_matched = True
        remainder = p[len(prefix):]
        if not remainder:
            continue
        first_segment, _, rest = remainder.partition("/")
        entries[first_segment] = entries.get(first_segment, False) or bool(rest)

    if not entries:
        if normalized and not prefix_matched:
            return f"No such directory: {path!r}. Use search_code or the repository root (empty path) to find valid paths."
        return "This directory is empty."

    return "\n".join(f"{name}/" if is_dir else name for name, is_dir in sorted(entries.items()))


async def read_file(db: AsyncSession, repo_id: UUID, path: str) -> str:
    result = await db.execute(select(File).where(File.repo_id == repo_id, File.path == path))
    file = result.scalar_one_or_none()
    if file is None:
        return f"No such file: {path!r}. Use list_directory or search_code to find the correct path."

    content = truncate_to_token_budget(file.content, MAX_CONTEXT_TOKENS)
    return f"### {path}\n```\n{content}\n```"
