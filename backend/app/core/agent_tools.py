from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.embeddings import embed_text
from app.core.llm import ToolSpec
from app.core.search import hybrid_search
from app.core.token_budget import (
    MAX_CONTEXT_TOKENS,
    extract_outline,
    fits_token_budget,
    truncate_around_match,
    truncate_to_token_budget,
)
from app.db.models import File

# Descriptions below are deliberately terse -- these ToolSpecs are
# serialized into the provider's tool/function-schema JSON on every single
# LLM call, same token-conservation pass as agent.py's SYSTEM_PROMPT
# constants (see that file's comment for the quota-exhaustion context).
# Kept short enough to matter, not so short tool selection accuracy
# regresses -- each still states what it returns and when to prefer it.
SEARCH_CODE_TOOL_SPEC = ToolSpec(
    name="search_code",
    description=(
        "Search repo code by natural-language query. Returns ranked chunks with file path, "
        "symbol, line range. Use when you don't know which file has what you need."
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
        "List files/subdirectories directly inside a repo directory (not recursive). Empty "
        "string = repo root. Use first for broad questions to see the overall layout."
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
        "Read one file's contents, given its exact path (from search_code/list_directory output). "
        "Use when a chunked search_code snippet isn't enough context. ALWAYS pass query with the "
        "keyword you're actually looking for (e.g. \"pytest\", \"dependencies\") when reading a "
        "config/manifest/CI file (pyproject.toml, package.json, etc) -- these are often too long to "
        "read in full, and without query you only get a structural outline (section/def names), not "
        "the actual values. query jumps straight to the matching section instead."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Exact file path relative to the repo root"},
            "query": {
                "type": "string",
                "description": (
                    "The keyword/topic you're looking for in this file (e.g. \"pytest\", "
                    "\"dependencies\"). Always provide this for a config/manifest file."
                ),
            },
        },
        "required": ["path"],
    },
)


# A single chunk's content can itself be well over 40 lines (a large
# function/class chunk) -- capping each chunk individually, not just the
# combined result's overall token budget below, keeps every single excerpt
# a genuinely skimmable size instead of one chunk quietly eating the whole
# budget and starving the rest.
_MAX_SNIPPET_LINES = 40


def _truncate_snippet(content: str, max_lines: int = _MAX_SNIPPET_LINES) -> str:
    lines = content.splitlines()
    if len(lines) <= max_lines:
        return content
    return "\n".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines truncated)"


async def search_code(
    db: AsyncSession, repo_id: UUID, query: str, limit: int = 2, max_tokens: int = MAX_CONTEXT_TOKENS
) -> str:
    # limit=2: the chat agent (the only real caller -- see chat.py's
    # search_fn) gets only the top 2 most relevant chunks, not the top 5 --
    # part of a strict token-conservation pass under real, live-confirmed
    # daily-quota exhaustion on both configured LLM providers (see
    # chat.py's MAX_HISTORY_TOKENS comment for the full context). Every
    # extra chunk is prompt tokens spent on the 3rd/4th/5th-most-relevant
    # result instead of headroom for the answer itself.
    query_embedding = await run_in_threadpool(embed_text, query)
    results = await hybrid_search(db, repo_id, query_text=query, query_embedding=query_embedding, limit=limit)
    if not results:
        return "No matching code found for this query."

    blocks = []
    for r in results:
        symbol = f" ({r.symbol_name})" if r.symbol_name else ""
        snippet = _truncate_snippet(r.content)
        blocks.append(f"### {r.file_path}:{r.start_line}-{r.end_line}{symbol}\n```\n{snippet}\n```")
    # Several chunks concatenated (up to `limit`) can still add up well past
    # a single tool result's fair share of a request's token budget even
    # after the per-chunk line cap above -- see token_budget.py for why
    # this cap exists (a 413 "tokens per minute" failure this was added to
    # prevent). `max_tokens` defaults to the shared one-shot budget but
    # chat.py passes a much tighter one (see CHAT_TOOL_RESULT_MAX_TOKENS) --
    # chat can accumulate several of these results in one turn (one per
    # tool call, up to MAX_TOOL_ITERATIONS), while every other caller here
    # issues a single one-shot prompt.
    return truncate_to_token_budget("\n\n".join(blocks), max_tokens)


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


async def read_file(
    db: AsyncSession, repo_id: UUID, path: str, query: str | None = None, max_tokens: int = MAX_CONTEXT_TOKENS
) -> str:
    result = await db.execute(select(File).where(File.repo_id == repo_id, File.path == path))
    file = result.scalar_one_or_none()
    if file is None:
        return f"No such file: {path!r}. Use list_directory or search_code to find the correct path."

    # `query` lets the caller ask for the section of a long file that
    # actually matters instead of always the top -- see
    # truncate_around_match's docstring for why this exists (a relevant
    # section past a tight budget's cutoff is otherwise invisible no matter
    # how the budget is sized, purely because of where it sits in the
    # file). Falls back to the from-the-top behavior on its own whenever
    # `query` is empty or doesn't match anything.
    if query:
        content = truncate_around_match(file.content, query, max_tokens)
    elif not fits_token_budget(file.content, max_tokens) and (outline := extract_outline(file.content, max_tokens)):
        # No query given AND the file doesn't fit as-is: a from-the-top
        # truncation risks showing nothing but boilerplate (see
        # extract_outline's docstring for the motivating pyproject.toml
        # case) -- a structural outline is a strictly more useful default
        # when one is available, and it directly tells the model what
        # `query` to pass next if it needs a section in full.
        content = (
            f"{outline}\n\n(No query given, so this is a structural outline, not full content -- "
            "pass query with a keyword to read a specific section in full.)"
        )
    else:
        content = truncate_to_token_budget(file.content, max_tokens)
    return f"### {path}\n```\n{content}\n```"
