import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import logger
from app.models import (
    Document,
    DocumentChunk,
    DocumentProcessing,
    DocumentStatus,
    ProcessingStatus,
)
from app.schemas.processing import ProcessingResult
from app.services.document_extraction import extract_text
from app.services.text_chunking import TextChunk, chunk_segments


class DocumentNotFoundError(Exception):
    pass


class ProcessingConflictError(Exception):
    pass


def _extract_and_chunk(storage_path: str) -> list[TextChunk]:
    segments = extract_text(Path(storage_path))
    return chunk_segments(segments)


async def _persist_chunks(
    db: AsyncSession,
    document_id: uuid.UUID,
    attempt_id: uuid.UUID,
    chunks: list[TextChunk],
) -> None:
    await db.execute(
        delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
    )
    for chunk in chunks:
        db.add(
            DocumentChunk(
                document_id=document_id,
                chunk_index=chunk.chunk_index,
                content=chunk.text,
                page_number=chunk.page_number,
                token_count=None,
            )
        )

    now = datetime.now(timezone.utc)
    await db.execute(
        update(DocumentProcessing)
        .where(DocumentProcessing.id == attempt_id)
        .values(status=ProcessingStatus.COMPLETED, completed_at=now)
    )
    await db.execute(
        update(Document)
        .where(Document.id == document_id)
        .values(status=DocumentStatus.COMPLETED)
    )
    await db.commit()


async def _mark_attempt_failed(
    db: AsyncSession,
    attempt_id: uuid.UUID,
    document_id: uuid.UUID,
    message: str,
) -> None:
    now = datetime.now(timezone.utc)
    await db.execute(
        update(DocumentProcessing)
        .where(DocumentProcessing.id == attempt_id)
        .values(
            status=ProcessingStatus.FAILED,
            completed_at=now,
            error_message=message[:2000],
        )
    )
    await db.execute(
        update(Document)
        .where(Document.id == document_id)
        .values(status=DocumentStatus.FAILED)
    )
    await db.commit()


async def process_document(
    document_id: uuid.UUID, db: AsyncSession
) -> ProcessingResult:
    """Run the extraction/chunking pipeline for a document.

    Stage A locks the document row, validates state, creates the processing
    attempt and commits. Stage B extracts/chunks in a threadpool, then
    persists chunks and completion atomically. Any Stage B failure rolls
    back, then marks the attempt and document FAILED in a new transaction.
    """
    document = (
        await db.execute(
            select(Document)
            .where(Document.id == document_id)
            .with_for_update()
        )
    ).scalar_one_or_none()

    if document is None:
        raise DocumentNotFoundError(f"Document {document_id} not found")
    if document.status == DocumentStatus.PROCESSING:
        raise ProcessingConflictError("Document is already being processed")
    if document.status == DocumentStatus.COMPLETED:
        raise ProcessingConflictError("Document has already been processed")

    max_attempt = await db.scalar(
        select(func.max(DocumentProcessing.attempt_number)).where(
            DocumentProcessing.document_id == document.id
        )
    )
    attempt_number = (max_attempt or 0) + 1

    attempt = DocumentProcessing(
        document_id=document.id,
        attempt_number=attempt_number,
        status=ProcessingStatus.PROCESSING,
    )
    document.status = DocumentStatus.PROCESSING
    db.add(attempt)
    await db.flush()

    doc_id = document.id
    attempt_id = attempt.id
    storage_path = document.storage_path
    await db.commit()

    chunks: list[TextChunk] = []
    try:
        chunks = await asyncio.to_thread(_extract_and_chunk, storage_path)
        await _persist_chunks(db, doc_id, attempt_id, chunks)
    except Exception as e:
        await db.rollback()
        message = f"{type(e).__name__}: {e}"
        logger.error(
            "Document %s processing attempt %s failed: %s",
            doc_id,
            attempt_number,
            message,
        )
        try:
            await _mark_attempt_failed(db, attempt_id, doc_id, message)
        except Exception:
            logger.exception(
                "Failed to record processing failure for document %s", doc_id
            )
        raise

    return ProcessingResult(
        document_id=doc_id,
        document_status=DocumentStatus.COMPLETED,
        attempt_number=attempt_number,
        processing_status=ProcessingStatus.COMPLETED,
        chunks_created=len(chunks),
        error_message=None,
    )
