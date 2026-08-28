from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CodeChunk

RRF_K = 60


@dataclass
class SearchResult:
    chunk_id: UUID
    file_path: str
    symbol_name: str | None
    node_type: str
    start_line: int
    end_line: int
    content: str
    score: float


def reciprocal_rank_fusion(*ranked_id_lists: list[UUID], k: int = RRF_K) -> list[tuple[UUID, float]]:
    scores: dict[UUID, float] = {}
    for ranked_ids in ranked_id_lists:
        for rank, chunk_id in enumerate(ranked_ids, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


async def vector_search(db: AsyncSession, repo_id: UUID, query_embedding: list[float], limit: int) -> list[CodeChunk]:
    result = await db.execute(
        select(CodeChunk)
        .where(CodeChunk.repo_id == repo_id)
        .order_by(CodeChunk.embedding.cosine_distance(query_embedding))
        .limit(limit)
    )
    return list(result.scalars().all())


async def keyword_search(db: AsyncSession, repo_id: UUID, query_text: str, limit: int) -> list[CodeChunk]:
    # NOTE: each text() clause below declares its own ":query" bindparam.
    # Select.params() only fills bindparams it can resolve at the point
    # they're attached to the statement tree and does not reliably
    # propagate a single value across multiple independent text()
    # constructs (verified: compiling the brief's original .params(...)
    # form left the "query" bind resolved to None). Binding the value
    # directly on each text() clause via .bindparams() is unambiguous.
    match_clause = text("content_tsv @@ plainto_tsquery('english', :query)").bindparams(query=query_text)
    rank_clause = text("ts_rank(content_tsv, plainto_tsquery('english', :query)) DESC").bindparams(query=query_text)
    result = await db.execute(
        select(CodeChunk)
        .where(CodeChunk.repo_id == repo_id, match_clause)
        .order_by(rank_clause)
        .limit(limit)
    )
    return list(result.scalars().all())


async def hybrid_search(
    db: AsyncSession, repo_id: UUID, query_text: str, query_embedding: list[float], limit: int = 10
) -> list[SearchResult]:
    vector_results = await vector_search(db, repo_id, query_embedding, limit=limit * 2)
    keyword_results = await keyword_search(db, repo_id, query_text, limit=limit * 2)

    chunks_by_id = {c.id: c for c in [*vector_results, *keyword_results]}
    fused = reciprocal_rank_fusion([c.id for c in vector_results], [c.id for c in keyword_results])

    results: list[SearchResult] = []
    for chunk_id, score in fused[:limit]:
        chunk = chunks_by_id[chunk_id]
        results.append(
            SearchResult(
                chunk_id=chunk.id,
                file_path=chunk.file_path,
                symbol_name=chunk.symbol_name,
                node_type=chunk.node_type.value,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                content=chunk.content,
                score=score,
            )
        )
    return results
