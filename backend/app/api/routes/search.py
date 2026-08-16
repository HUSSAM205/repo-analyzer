from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user
from app.core.embeddings import embed_text
from app.core.search import hybrid_search
from app.db.models import Repo, User
from app.db.session import get_db
from app.schemas.search import SearchRequest, SearchResponse, SearchResultItem

router = APIRouter(prefix="/api/v1/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search_repo(
    payload: SearchRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SearchResponse:
    repo = await db.get(Repo, payload.repo_id)
    if repo is None or repo.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repo not found")

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
