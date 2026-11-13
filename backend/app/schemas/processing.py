import uuid

from pydantic import BaseModel

from app.models import DocumentStatus, ProcessingStatus


class ProcessingResult(BaseModel):
    document_id: uuid.UUID
    document_status: DocumentStatus
    attempt_number: int
    processing_status: ProcessingStatus
    chunks_created: int
    error_message: str | None = None
