from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.embeddings import embed_text
from app.core.llm import ToolSpec
from app.core.search import hybrid_search

SEARCH_CODE_TOOL_SPEC = ToolSpec(
    name="search_code",
    description=(
        "Search the repository's code for content relevant to a natural-language "
        "query. Returns ranked code chunks with file path, symbol name, and line "
        "range. Always use this before answering questions about specific code."
    ),
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string", "description": "What to search for"}},
        "required": ["query"],
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
    return "\n\n".join(blocks)
