import uuid
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.models import EmbeddingStatus


class EmbeddingResult(BaseModel):
    document_id: uuid.UUID
    embedding_status: EmbeddingStatus
    embedding_model: str
    total_chunks: int
    embedded_chunks: int
    skipped_chunks: int
    error_message: str | None = None


QueryText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]


class SearchRequest(BaseModel):
    query: QueryText
    top_k: int = Field(default=10, ge=1, le=50)
    document_id: uuid.UUID | None = None


class SearchResultItem(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    chunk_index: int
    page_number: int | None
    content: str
    score: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultItem]
