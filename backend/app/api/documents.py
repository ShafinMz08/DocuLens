from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import logger
from app.db.session import get_db
from app.models import Document, DocumentStatus
from app.schemas.document import DocumentListResponse, DocumentOut
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
