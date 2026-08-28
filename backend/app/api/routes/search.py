from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user
from app.config import get_settings
from app.core.embeddings import embed_text
from app.core.search import hybrid_search
from app.db.models import Repo, User
from app.db.session import get_db
from app.schemas.search import SearchRequest, SearchResponse, SearchResultItem

router = APIRouter(prefix="/api/v1/search", tags=["search"])
settings = get_settings()


@router.post("", response_model=SearchResponse)
async def search_repo(
    payload: SearchRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SearchResponse:
    repo = await db.get(Repo, payload.repo_id)
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repo not found")

    # chat.py already excludes search_code from the agent's tools entirely
    # when embedding is disabled (see Settings.enable_embedding) -- this is
    # the one other path into the same embedding step. Without this guard,
    # calling this route directly would trigger loading the ~500MB CodeBERT
    # model on a deployment that explicitly disabled embedding specifically
    # because that model doesn't fit its memory budget (see render.yaml).
    if not settings.enable_embedding:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Code search is currently disabled on this deployment.",
        )

    query_embedding = await run_in_threadpool(embed_text, payload.query)
    results = await hybrid_search(
        db, payload.repo_id, query_text=payload.query, query_embedding=query_embedding, limit=payload.limit
    )
    return SearchResponse(
        results=[
            SearchResultItem(
                chunk_id=r.chunk_id, file_path=r.file_path, symbol_name=r.symbol_name, node_type=r.node_type,
                start_line=r.start_line, end_line=r.end_line, content=r.content, score=r.score,
            )
            for r in results
        ]
    )
