import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import logger
from app.db.session import get_db
from app.models import Document, DocumentStatus, EmbeddingStatus
from app.schemas.document import DocumentListResponse, DocumentOut
from app.schemas.processing import ProcessingResult
from app.schemas.search import EmbeddingResult
from app.services import document_processing, embeddings
from app.services.document_processing import (
    DocumentNotFoundError,
    ProcessingConflictError,
)
from app.services.embeddings import (
    EmbeddingConflictError,
    EmbeddingError,
    EmbeddingNotReadyError,
)
from app.services.document_storage import (
    FileTooLargeError,
    UploadValidationError,
    store_uploaded_file,
)

router = APIRouter()


@router.post(
    "/upload",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        stored = await store_uploaded_file(file)
    except FileTooLargeError as e:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(e))
    except UploadValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except OSError:
        logger.exception("Failed to store uploaded file")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store uploaded file",
        )

    document = Document(
        original_filename=stored.original_filename,
        stored_filename=stored.stored_filename,
        content_type=stored.content_type,
        file_size_bytes=stored.file_size_bytes,
        storage_path=stored.storage_path,
        status=DocumentStatus.UPLOADED,
    )
    db.add(document)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        Path(stored.storage_path).unlink(missing_ok=True)
        logger.exception("Failed to persist document metadata")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save document metadata",
        )
    await db.refresh(document)
    return document


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    total = await db.scalar(select(func.count()).select_from(Document))
    result = await db.execute(
        select(Document)
        .order_by(Document.created_at.desc(), Document.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return DocumentListResponse(
        items=result.scalars().all(),
        total=total or 0,
        skip=skip,
        limit=limit,
    )


@router.post("/{document_id}/process", response_model=ProcessingResult)
async def process_document_endpoint(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await document_processing.process_document(document_id, db)
    except DocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )
    except ProcessingConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(e)
        )
    except Exception:
        logger.exception("Document %s processing failed", document_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document processing failed",
        )

    # Automatically embed the freshly persisted chunks. An embedding
    # failure never fails extraction: chunks stay persisted and the
    # outcome is reported through the embedding fields.
    embedding_fields = {
        "embedding_status": EmbeddingStatus.PENDING,
        "embedded_chunks": 0,
        "total_chunks": result.chunks_created,
        "skipped_chunks": None,
        "embedding_error": None,
    }
    try:
        embedding = await embeddings.embed_document(document_id, db)
        embedding_fields = {
            "embedding_status": embedding.embedding_status,
            "embedded_chunks": embedding.embedded_chunks,
            "total_chunks": embedding.total_chunks,
            "skipped_chunks": embedding.skipped_chunks,
            "embedding_error": embedding.error_message,
        }
    except embeddings.EmbeddingConflictError:
        embedding_fields["embedding_status"] = EmbeddingStatus.PROCESSING
    except embeddings.EmbeddingError as e:
        logger.exception(
            "Automatic embedding failed for document %s", document_id
        )
        embedding_fields.update(
            {
                "embedding_status": EmbeddingStatus.FAILED,
                "embedded_chunks": e.embedded_chunks or 0,
                "total_chunks": (
                    e.total_chunks
                    if e.total_chunks is not None
                    else result.chunks_created
                ),
                "skipped_chunks": e.skipped_chunks,
                "embedding_error": "Embedding generation failed",
            }
        )

    return result.model_copy(update=embedding_fields)


@router.post("/{document_id}/embed", response_model=EmbeddingResult)
async def embed_document_endpoint(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await embeddings.embed_document(document_id, db)
    except DocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )
    except EmbeddingNotReadyError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(e)
        )
    except EmbeddingConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(e)
        )
    except EmbeddingError:
        logger.exception("Document %s embedding failed", document_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document embedding failed",
        )
