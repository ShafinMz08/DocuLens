import uuid

from pydantic import BaseModel

from app.models import DocumentStatus, EmbeddingStatus, ProcessingStatus


class ProcessingResult(BaseModel):
    document_id: uuid.UUID
    document_status: DocumentStatus
    attempt_number: int
    processing_status: ProcessingStatus
    chunks_created: int
    error_message: str | None = None
    embedding_status: EmbeddingStatus | None = None
    embedded_chunks: int = 0
    total_chunks: int | None = None
    skipped_chunks: int | None = None
    embedding_error: str | None = None
