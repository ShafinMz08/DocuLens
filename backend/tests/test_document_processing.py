import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.models import (
    Document,
    DocumentChunk,
    DocumentProcessing,
    DocumentStatus,
    ProcessingStatus,
)
from app.services import document_processing
from app.services.document_extraction import ExtractionError
from app.services.document_processing import (
    DocumentNotFoundError,
    ProcessingConflictError,
    process_document,
)
from app.services.text_chunking import TextChunk
from tests.test_extraction import make_docx_bytes, make_pdf_bytes


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


def _doc_kwargs(storage_path: str, **overrides) -> dict:
    fields = {
        "original_filename": "test-doc.pdf",
        "stored_filename": f"test-proc-{uuid.uuid4().hex}.pdf",
        "content_type": "application/pdf",
        "file_size_bytes": 128,
        "storage_path": storage_path,
        "status": DocumentStatus.UPLOADED,
    }
    fields.update(overrides)
    return fields


async def _create_document(session: AsyncSession, storage_path: str, **overrides):
    doc = Document(**_doc_kwargs(storage_path, **overrides))
    session.add(doc)
    await session.commit()
    return doc.id


async def _cleanup_documents(session: AsyncSession, doc_ids: list) -> None:
    if doc_ids:
        await session.execute(delete(Document).where(Document.id.in_(doc_ids)))
        await session.commit()


async def _get_chunks(session: AsyncSession, doc_id) -> list[DocumentChunk]:
    result = await session.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == doc_id)
        .order_by(DocumentChunk.chunk_index)
    )
    return list(result.scalars().all())


async def _get_attempts(session: AsyncSession, doc_id) -> list[DocumentProcessing]:
    result = await session.execute(
        select(DocumentProcessing)
        .where(DocumentProcessing.document_id == doc_id)
        .order_by(DocumentProcessing.attempt_number)
    )
    return list(result.scalars().all())


async def _get_document(session: AsyncSession, doc_id) -> Document:
    return await session.scalar(select(Document).where(Document.id == doc_id))


async def test_process_pdf_success(db_session: AsyncSession, tmp_path):
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(make_pdf_bytes(["First page text", "Second page text"]))
    doc_id = await _create_document(db_session, str(pdf_path))

    try:
        result = await process_document(doc_id, db_session)

        assert result.document_id == doc_id
        assert result.document_status == DocumentStatus.COMPLETED
        assert result.attempt_number == 1
        assert result.processing_status == ProcessingStatus.COMPLETED
        assert result.chunks_created >= 1
        assert result.error_message is None

        chunks = await _get_chunks(db_session, doc_id)
        assert len(chunks) == result.chunks_created
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
        assert {c.page_number for c in chunks} == {1, 2}
        assert all(c.token_count is None for c in chunks)

        doc = await _get_document(db_session, doc_id)
        assert doc.status == DocumentStatus.COMPLETED

        attempts = await _get_attempts(db_session, doc_id)
        assert len(attempts) == 1
        assert attempts[0].status == ProcessingStatus.COMPLETED
        assert attempts[0].attempt_number == 1
        assert attempts[0].completed_at is not None
    finally:
        await _cleanup_documents(db_session, [doc_id])


async def test_process_txt_success_multiple_chunks(
    db_session: AsyncSession, tmp_path
):
    txt_path = tmp_path / "notes.txt"
    txt_path.write_text("word " * 400, encoding="utf-8")
    doc_id = await _create_document(
        db_session, str(txt_path), content_type="text/plain",
        original_filename="notes.txt",
    )

    try:
        result = await process_document(doc_id, db_session)

        assert result.chunks_created > 1
        chunks = await _get_chunks(db_session, doc_id)
        assert len(chunks) == result.chunks_created
        assert all(c.page_number is None for c in chunks)
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
        # content order preserved across chunks
        combined = " ".join(c.content for c in chunks)
        assert "word" in combined
    finally:
        await _cleanup_documents(db_session, [doc_id])


async def test_process_docx_success(db_session: AsyncSession, tmp_path):
    docx_path = tmp_path / "doc.docx"
    docx_path.write_bytes(make_docx_bytes())
    doc_id = await _create_document(
        db_session, str(docx_path),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        original_filename="doc.docx",
    )

    try:
        result = await process_document(doc_id, db_session)
        assert result.chunks_created >= 1
        chunks = await _get_chunks(db_session, doc_id)
        assert all(c.page_number is None for c in chunks)
        assert any("Introduction paragraph" in c.content for c in chunks)
    finally:
        await _cleanup_documents(db_session, [doc_id])


async def test_missing_document_raises(db_session: AsyncSession):
    with pytest.raises(DocumentNotFoundError):
        await process_document(uuid.uuid4(), db_session)


async def test_completed_document_rejected(db_session: AsyncSession, tmp_path):
    txt_path = tmp_path / "a.txt"
    txt_path.write_text("hello world", encoding="utf-8")
    doc_id = await _create_document(db_session, str(txt_path))

    try:
        await process_document(doc_id, db_session)
        with pytest.raises(ProcessingConflictError):
            await process_document(doc_id, db_session)

        attempts = await _get_attempts(db_session, doc_id)
        assert len(attempts) == 1
    finally:
        await _cleanup_documents(db_session, [doc_id])


async def test_processing_document_rejected(db_session: AsyncSession, tmp_path):
    txt_path = tmp_path / "b.txt"
    txt_path.write_text("hello world", encoding="utf-8")
    doc_id = await _create_document(db_session, str(txt_path))

    try:
        await db_session.execute(
            update(Document)
            .where(Document.id == doc_id)
            .values(status=DocumentStatus.PROCESSING)
        )
        await db_session.commit()

        with pytest.raises(ProcessingConflictError):
            await process_document(doc_id, db_session)

        attempts = await _get_attempts(db_session, doc_id)
        assert len(attempts) == 0
    finally:
        await _cleanup_documents(db_session, [doc_id])


async def test_extraction_failure_marks_failed(
    db_session: AsyncSession, tmp_path
):
    missing = tmp_path / "does-not-exist.pdf"
    doc_id = await _create_document(db_session, str(missing))

    try:
        with pytest.raises(ExtractionError):
            await process_document(doc_id, db_session)

        doc = await _get_document(db_session, doc_id)
        assert doc.status == DocumentStatus.FAILED

        attempts = await _get_attempts(db_session, doc_id)
        assert len(attempts) == 1
        assert attempts[0].status == ProcessingStatus.FAILED
        assert attempts[0].error_message
        assert attempts[0].completed_at is not None

        assert await _get_chunks(db_session, doc_id) == []
    finally:
        await _cleanup_documents(db_session, [doc_id])


async def test_chunking_failure_marks_failed(
    db_session: AsyncSession, tmp_path, monkeypatch
):
    txt_path = tmp_path / "c.txt"
    txt_path.write_text("hello world", encoding="utf-8")
    doc_id = await _create_document(db_session, str(txt_path))

    def boom(_segments):
        raise RuntimeError("chunking exploded")

    monkeypatch.setattr(document_processing, "chunk_segments", boom)

    try:
        with pytest.raises(RuntimeError, match="chunking exploded"):
            await process_document(doc_id, db_session)

        doc = await _get_document(db_session, doc_id)
        assert doc.status == DocumentStatus.FAILED

        attempts = await _get_attempts(db_session, doc_id)
        assert attempts[0].status == ProcessingStatus.FAILED
        assert "chunking exploded" in attempts[0].error_message
        assert await _get_chunks(db_session, doc_id) == []
    finally:
        await _cleanup_documents(db_session, [doc_id])


async def test_persistence_failure_rolls_back_chunks(
    db_session: AsyncSession, tmp_path, monkeypatch
):
    txt_path = tmp_path / "d.txt"
    txt_path.write_text("hello world", encoding="utf-8")
    doc_id = await _create_document(db_session, str(txt_path))

    def bad_chunks(_segments):
        return [
            TextChunk(chunk_index=0, text="first", page_number=None),
            TextChunk(chunk_index=0, text="duplicate index", page_number=None),
        ]

    monkeypatch.setattr(document_processing, "chunk_segments", bad_chunks)

    try:
        with pytest.raises(Exception):
            await process_document(doc_id, db_session)

        # no partial chunks persisted
        assert await _get_chunks(db_session, doc_id) == []

        doc = await _get_document(db_session, doc_id)
        assert doc.status == DocumentStatus.FAILED

        attempts = await _get_attempts(db_session, doc_id)
        assert attempts[0].status == ProcessingStatus.FAILED
    finally:
        await _cleanup_documents(db_session, [doc_id])


async def test_retry_after_failure_sequential_attempts(
    db_session: AsyncSession, tmp_path, monkeypatch
):
    txt_path = tmp_path / "e.txt"
    txt_path.write_text("retry me " * 300, encoding="utf-8")
    doc_id = await _create_document(db_session, str(txt_path))

    def boom(_segments):
        raise RuntimeError("temporary failure")

    monkeypatch.setattr(document_processing, "chunk_segments", boom)

    try:
        with pytest.raises(RuntimeError):
            await process_document(doc_id, db_session)

        # insert a stale chunk that must be replaced on retry
        db_session.add(
            DocumentChunk(
                document_id=doc_id, chunk_index=0, content="stale chunk"
            )
        )
        await db_session.commit()

        monkeypatch.undo()
        result = await process_document(doc_id, db_session)

        assert result.attempt_number == 2
        assert result.processing_status == ProcessingStatus.COMPLETED

        attempts = await _get_attempts(db_session, doc_id)
        assert [a.attempt_number for a in attempts] == [1, 2]
        assert attempts[0].status == ProcessingStatus.FAILED
        assert attempts[1].status == ProcessingStatus.COMPLETED

        chunks = await _get_chunks(db_session, doc_id)
        assert len(chunks) == result.chunks_created
        assert all(c.content != "stale chunk" for c in chunks)
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))

        doc = await _get_document(db_session, doc_id)
        assert doc.status == DocumentStatus.COMPLETED
    finally:
        await _cleanup_documents(db_session, [doc_id])


async def test_empty_extraction_marks_failed(
    db_session: AsyncSession, tmp_path
):
    txt_path = tmp_path / "empty.txt"
    txt_path.write_text("   \n  ", encoding="utf-8")
    doc_id = await _create_document(db_session, str(txt_path))

    try:
        with pytest.raises(ExtractionError):
            await process_document(doc_id, db_session)

        doc = await _get_document(db_session, doc_id)
        assert doc.status == DocumentStatus.FAILED
        attempts = await _get_attempts(db_session, doc_id)
        assert attempts[0].status == ProcessingStatus.FAILED
    finally:
        await _cleanup_documents(db_session, [doc_id])
