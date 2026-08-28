import uuid

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    repo_id: uuid.UUID
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=10, ge=1, le=50)


class SearchResultItem(BaseModel):
    chunk_id: uuid.UUID
    file_path: str
    symbol_name: str | None
    node_type: str
    start_line: int
    end_line: int
    content: str
    score: float


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
