import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.session import Base
from app.models import (
    Document,
    DocumentChunk,
    DocumentProcessing,
    DocumentStatus,
    ProcessingStatus,
)


@pytest_asyncio.fixture
async def db_session():
    test_database_url = settings.TEST_DATABASE_URL

    if not test_database_url:
        raise RuntimeError(
            "TEST_DATABASE_URL is required. Refusing to run tests."
        )

    test_database_name = make_url(test_database_url).database

    if test_database_name != "doculens_test":
        raise RuntimeError(
            f"Unsafe test database: {test_database_name}. "
            "Expected doculens_test."
        )

    engine = create_async_engine(test_database_url)
    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


def _make_document(**overrides) -> Document:
    fields = {
        "original_filename": "report.pdf",
        "stored_filename": f"test-{uuid.uuid4().hex}.pdf",
        "content_type": "application/pdf",
        "file_size_bytes": 1024,
        "storage_path": f"/tmp/{uuid.uuid4().hex}.pdf",
    }
    fields.update(overrides)
    return Document(**fields)


async def _delete_document(session: AsyncSession, document_id) -> None:
    await session.rollback()
    await session.execute(delete(Document).where(Document.id == document_id))
    await session.commit()


def test_models_registered_in_metadata():
    tables = Base.metadata.tables
    assert "documents" in tables
    assert "document_chunks" in tables
    assert "document_processing" in tables


async def test_document_creation(db_session: AsyncSession):
    doc = _make_document()
    try:
        db_session.add(doc)
        await db_session.commit()
        await db_session.refresh(doc)

        assert doc.id is not None
        assert doc.status == DocumentStatus.UPLOADED
        assert doc.created_at is not None
        assert doc.created_at.tzinfo is not None
        assert doc.updated_at is not None
        assert doc.updated_at.tzinfo is not None
    finally:
        await _delete_document(db_session, doc.id)


async def test_document_chunk_relationship(db_session: AsyncSession):
    doc = _make_document()
    try:
        doc.chunks = [
            DocumentChunk(chunk_index=0, content="first chunk", page_number=1),
            DocumentChunk(chunk_index=1, content="second chunk", token_count=42),
        ]
        db_session.add(doc)
        await db_session.commit()
        await db_session.refresh(doc, ["chunks"])

        assert len(doc.chunks) == 2
        assert [c.chunk_index for c in doc.chunks] == [0, 1]
        assert doc.chunks[0].document_id == doc.id
        assert doc.chunks[0].document is doc
        assert doc.chunks[1].page_number is None
        assert doc.chunks[1].token_count == 42
    finally:
        await _delete_document(db_session, doc.id)


async def test_document_processing_relationship(db_session: AsyncSession):
    doc = _make_document()
    try:
        doc.processing_attempts = [
            DocumentProcessing(attempt_number=1, status=ProcessingStatus.COMPLETED),
            DocumentProcessing(
                attempt_number=2,
                status=ProcessingStatus.FAILED,
                error_message="extraction failed",
            ),
        ]
        db_session.add(doc)
        await db_session.commit()
        await db_session.refresh(doc, ["processing_attempts"])

        assert len(doc.processing_attempts) == 2
        assert [p.attempt_number for p in doc.processing_attempts] == [1, 2]
        assert doc.processing_attempts[0].document is doc
        assert doc.processing_attempts[1].error_message == "extraction failed"
        assert doc.processing_attempts[1].completed_at is None
    finally:
        await _delete_document(db_session, doc.id)


async def test_unique_chunk_index_constraint(db_session: AsyncSession):
    doc = _make_document()
    doc_id = None
    try:
        doc.chunks = [DocumentChunk(chunk_index=0, content="only chunk")]
        db_session.add(doc)
        await db_session.commit()
        doc_id = doc.id

        db_session.add(
            DocumentChunk(document_id=doc_id, chunk_index=0, content="duplicate index")
        )
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()
    finally:
        if doc_id is not None:
            await _delete_document(db_session, doc_id)


async def test_unique_processing_attempt_constraint(db_session: AsyncSession):
    doc = _make_document()
    doc_id = None
    try:
        doc.processing_attempts = [DocumentProcessing(attempt_number=1)]
        db_session.add(doc)
        await db_session.commit()
        doc_id = doc.id

        db_session.add(DocumentProcessing(document_id=doc_id, attempt_number=1))
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()
    finally:
        if doc_id is not None:
            await _delete_document(db_session, doc_id)


async def test_cascade_delete_removes_chunks_and_processing(db_session: AsyncSession):
    doc = _make_document()
    doc_id = None
    try:
        doc.chunks = [DocumentChunk(chunk_index=0, content="chunk")]
        doc.processing_attempts = [DocumentProcessing(attempt_number=1)]
        db_session.add(doc)
        await db_session.commit()
        doc_id = doc.id
    finally:
        if doc_id is not None:
            await _delete_document(db_session, doc_id)

    chunk_count = await db_session.scalar(
        select(func.count())
        .select_from(DocumentChunk)
        .where(DocumentChunk.document_id == doc_id)
    )
    processing_count = await db_session.scalar(
        select(func.count())
        .select_from(DocumentProcessing)
        .where(DocumentProcessing.document_id == doc_id)
    )
    assert chunk_count == 0
    assert processing_count == 0
