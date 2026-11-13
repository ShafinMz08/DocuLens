import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.models import (
    Document,
    DocumentChunk,
    DocumentStatus,
    EmbeddingStatus,
)
from app.schemas.search import SearchRequest
from app.services import embeddings
from app.services.document_processing import DocumentNotFoundError
from app.services.embeddings import (
    EmbeddingConflictError,
    EmbeddingError,
    EmbeddingNotReadyError,
    embed_document,
    embedding_model_key,
    semantic_search,
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


def _vec(seed: float = 0.0) -> list[float]:
    vec = [0.0] * settings.EMBEDDING_DIMENSIONS
    vec[0] = seed
    return vec


def _unit_vec(index: int) -> list[float]:
    vec = [0.0] * settings.EMBEDDING_DIMENSIONS
    vec[index] = 1.0
    return vec


async def _create_document(
    session: AsyncSession,
    status: DocumentStatus = DocumentStatus.COMPLETED,
    chunk_contents: list[str] | None = None,
) -> uuid.UUID:
    doc = Document(
        original_filename="embed-test.pdf",
        stored_filename=f"embed-test-{uuid.uuid4().hex}.pdf",
        content_type="application/pdf",
        file_size_bytes=128,
        storage_path="/tmp/nonexistent.pdf",
        status=status,
    )
    session.add(doc)
    await session.flush()
    for i, content in enumerate(chunk_contents or []):
        session.add(
            DocumentChunk(
                document_id=doc.id,
                chunk_index=i,
                content=content,
            )
        )
    await session.commit()
    return doc.id


async def _cleanup(session: AsyncSession, doc_ids: list) -> None:
    if doc_ids:
        await session.execute(delete(Document).where(Document.id.in_(doc_ids)))
        await session.commit()


async def _get_document(session: AsyncSession, doc_id) -> Document:
    return await session.scalar(select(Document).where(Document.id == doc_id))


async def _get_chunks(session: AsyncSession, doc_id) -> list[DocumentChunk]:
    result = await session.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == doc_id)
        .order_by(DocumentChunk.chunk_index)
    )
    return list(result.scalars().all())


def _mock_embedder(vectors: list[list[float]] | None = None, calls: list | None = None):
    """Return an async fake for embeddings.embed_texts."""

    async def fake(texts: list[str]) -> list[list[float]]:
        if calls is not None:
            calls.append(list(texts))
        if vectors is not None:
            return vectors[: len(texts)] if len(vectors) >= len(texts) else [
                _unit_vec(i % settings.EMBEDDING_DIMENSIONS) for i in range(len(texts))
            ]
        return [_unit_vec(i % settings.EMBEDDING_DIMENSIONS) for i in range(len(texts))]

    return fake


async def test_embed_document_success(db_session: AsyncSession, monkeypatch):
    doc_id = await _create_document(
        db_session, chunk_contents=["alpha chunk", "beta chunk", "gamma chunk"]
    )
    calls = []
    monkeypatch.setattr(
        embeddings, "embed_texts", _mock_embedder(calls=calls)
    )

    try:
        result = await embed_document(doc_id, db_session)

        assert result.document_id == doc_id
        assert result.embedding_status == EmbeddingStatus.COMPLETED
        assert result.embedding_model == embedding_model_key()
        assert result.total_chunks == 3
        assert result.embedded_chunks == 3
        assert result.skipped_chunks == 0
        assert result.error_message is None

        assert len(calls) == 1
        assert calls[0] == ["alpha chunk", "beta chunk", "gamma chunk"]

        chunks = await _get_chunks(db_session, doc_id)
        assert all(c.embedding is not None for c in chunks)
        assert all(
            c.embedding_model == embedding_model_key() for c in chunks
        )
        assert all(len(c.embedding) == settings.EMBEDDING_DIMENSIONS for c in chunks)

        doc = await _get_document(db_session, doc_id)
        assert doc.embedding_status == EmbeddingStatus.COMPLETED
        assert doc.embedded_at is not None
        assert doc.embedding_error is None
    finally:
        await _cleanup(db_session, [doc_id])


async def test_embed_document_batches(db_session: AsyncSession, monkeypatch):
    doc_id = await _create_document(
        db_session,
        chunk_contents=[f"chunk {i}" for i in range(5)],
    )
    monkeypatch.setattr(settings, "EMBEDDING_BATCH_SIZE", 2)
    calls = []
    monkeypatch.setattr(embeddings, "embed_texts", _mock_embedder(calls=calls))

    try:
        result = await embed_document(doc_id, db_session)
        assert result.embedded_chunks == 5
        assert [len(c) for c in calls] == [2, 2, 1]
    finally:
        await _cleanup(db_session, [doc_id])


async def test_embed_document_repeat_is_idempotent(
    db_session: AsyncSession, monkeypatch
):
    doc_id = await _create_document(
        db_session, chunk_contents=["one", "two"]
    )
    calls = []
    monkeypatch.setattr(embeddings, "embed_texts", _mock_embedder(calls=calls))

    try:
        await embed_document(doc_id, db_session)
        result = await embed_document(doc_id, db_session)

        assert result.embedding_status == EmbeddingStatus.COMPLETED
        assert result.embedded_chunks == 2
        # second run found nothing pending: no additional embed calls
        assert len(calls) == 1
    finally:
        await _cleanup(db_session, [doc_id])


async def test_embed_document_missing(db_session: AsyncSession):
    with pytest.raises(DocumentNotFoundError):
        await embed_document(uuid.uuid4(), db_session)


async def test_embed_document_not_ready(db_session: AsyncSession):
    doc_id = await _create_document(
        db_session,
        status=DocumentStatus.UPLOADED,
        chunk_contents=["chunk"],
    )

    try:
        with pytest.raises(EmbeddingNotReadyError):
            await embed_document(doc_id, db_session)

        doc = await _get_document(db_session, doc_id)
        assert doc.embedding_status == EmbeddingStatus.PENDING
    finally:
        await _cleanup(db_session, [doc_id])


async def test_embed_document_conflict_while_processing(
    db_session: AsyncSession, monkeypatch
):
    doc_id = await _create_document(
        db_session, chunk_contents=["chunk"]
    )
    calls = []
    monkeypatch.setattr(embeddings, "embed_texts", _mock_embedder(calls=calls))

    try:
        await db_session.execute(
            update(Document)
            .where(Document.id == doc_id)
            .values(
                embedding_status=EmbeddingStatus.PROCESSING,
                embedding_started_at=datetime.now(timezone.utc),
            )
        )
        await db_session.commit()

        with pytest.raises(EmbeddingConflictError):
            await embed_document(doc_id, db_session)
        assert calls == []
    finally:
        await _cleanup(db_session, [doc_id])


async def test_embed_document_recovers_stale_processing(
    db_session: AsyncSession, monkeypatch
):
    doc_id = await _create_document(
        db_session, chunk_contents=["chunk"]
    )
    calls = []
    monkeypatch.setattr(embeddings, "embed_texts", _mock_embedder(calls=calls))

    try:
        stale = datetime.now(timezone.utc) - timedelta(
            seconds=settings.EMBEDDING_STALE_SECONDS + 60
        )
        await db_session.execute(
            update(Document)
            .where(Document.id == doc_id)
            .values(
                embedding_status=EmbeddingStatus.PROCESSING,
                embedding_started_at=stale,
            )
        )
        await db_session.commit()

        result = await embed_document(doc_id, db_session)
        assert result.embedding_status == EmbeddingStatus.COMPLETED
        assert result.embedded_chunks == 1
    finally:
        await _cleanup(db_session, [doc_id])


async def test_embed_document_failure_marks_failed(
    db_session: AsyncSession, monkeypatch
):
    doc_id = await _create_document(
        db_session, chunk_contents=["chunk one", "chunk two"]
    )

    async def boom(_texts):
        raise RuntimeError("onnx exploded")

    monkeypatch.setattr(embeddings, "embed_texts", boom)

    try:
        with pytest.raises(EmbeddingError):
            await embed_document(doc_id, db_session)

        doc = await _get_document(db_session, doc_id)
        assert doc.embedding_status == EmbeddingStatus.FAILED
        assert "onnx exploded" in doc.embedding_error

        chunks = await _get_chunks(db_session, doc_id)
        assert all(c.embedding is None for c in chunks)
    finally:
        await _cleanup(db_session, [doc_id])


async def test_embed_document_partial_failure_then_retry(
    db_session: AsyncSession, monkeypatch
):
    doc_id = await _create_document(
        db_session,
        chunk_contents=[f"chunk {i}" for i in range(4)],
    )
    monkeypatch.setattr(settings, "EMBEDDING_BATCH_SIZE", 2)

    calls = {"n": 0}

    async def flaky(texts):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("second batch failed")
        return [_unit_vec(i) for i in range(len(texts))]

    monkeypatch.setattr(embeddings, "embed_texts", flaky)

    try:
        with pytest.raises(EmbeddingError):
            await embed_document(doc_id, db_session)

        doc = await _get_document(db_session, doc_id)
        assert doc.embedding_status == EmbeddingStatus.FAILED

        # first batch was committed before the failure
        chunks = await _get_chunks(db_session, doc_id)
        embedded = [c for c in chunks if c.embedding is not None]
        assert len(embedded) == 2

        # retry completes the remaining chunks
        monkeypatch.setattr(embeddings, "embed_texts", _mock_embedder())
        result = await embed_document(doc_id, db_session)
        assert result.embedding_status == EmbeddingStatus.COMPLETED
        assert result.embedded_chunks == 4

        chunks = await _get_chunks(db_session, doc_id)
        assert all(c.embedding is not None for c in chunks)
        doc = await _get_document(db_session, doc_id)
        assert doc.embedding_status == EmbeddingStatus.COMPLETED
        assert doc.embedding_error is None
    finally:
        await _cleanup(db_session, [doc_id])


async def test_embed_document_model_change_reembeds(
    db_session: AsyncSession, monkeypatch
):
    doc_id = await _create_document(
        db_session, chunk_contents=["chunk"]
    )
    calls = []
    monkeypatch.setattr(embeddings, "embed_texts", _mock_embedder(calls=calls))

    try:
        await embed_document(doc_id, db_session)
        assert len(calls) == 1

        # simulate embeddings produced by a different model version
        await db_session.execute(
            update(DocumentChunk)
            .where(DocumentChunk.document_id == doc_id)
            .values(embedding_model="old-model@0")
        )
        await db_session.commit()

        result = await embed_document(doc_id, db_session)
        assert result.embedded_chunks == 1
        assert len(calls) == 2

        chunks = await _get_chunks(db_session, doc_id)
        assert chunks[0].embedding_model == embedding_model_key()
    finally:
        await _cleanup(db_session, [doc_id])


async def test_embed_document_skips_empty_chunks(
    db_session: AsyncSession, monkeypatch
):
    doc_id = await _create_document(
        db_session,
        chunk_contents=["real content", "   ", ""],
    )
    calls = []
    monkeypatch.setattr(embeddings, "embed_texts", _mock_embedder(calls=calls))

    try:
        result = await embed_document(doc_id, db_session)
        assert result.total_chunks == 3
        assert result.embedded_chunks == 1
        assert result.skipped_chunks == 2
        # only the non-empty chunk was sent to the model
        assert calls == [["real content"]]
    finally:
        await _cleanup(db_session, [doc_id])


async def _seed_chunk_with_vector(
    session: AsyncSession,
    doc_id: uuid.UUID,
    chunk_index: int,
    content: str,
    vector: list[float],
    model_key: str | None = None,
) -> uuid.UUID:
    chunk = DocumentChunk(
        document_id=doc_id,
        chunk_index=chunk_index,
        content=content,
        embedding=vector,
        embedding_model=model_key or embedding_model_key(),
    )
    session.add(chunk)
    await session.commit()
    return chunk.id


async def test_semantic_search_ranking_and_filter(
    db_session: AsyncSession, monkeypatch
):
    doc_a = await _create_document(db_session)
    doc_b = await _create_document(db_session)

    # controlled vectors with distinct cosine distances to the e0 query:
    # "closest" is parallel, "middle" is tilted, "farthest" is orthogonal.
    await _seed_chunk_with_vector(db_session, doc_a, 0, "closest", _unit_vec(0))
    await _seed_chunk_with_vector(
        db_session, doc_a, 1, "middle", [0.8, 0.2] + [0.0] * (settings.EMBEDDING_DIMENSIONS - 2)
    )
    await _seed_chunk_with_vector(db_session, doc_b, 0, "farthest", _unit_vec(2))

    async def fake_embed(texts):
        return [_unit_vec(0)]

    monkeypatch.setattr(embeddings, "embed_texts", fake_embed)

    try:
        resp = await semantic_search("find me", top_k=10, document_id=None, db=db_session)
        assert [r.content for r in resp.results] == ["closest", "middle", "farthest"]
        assert resp.results[0].score > resp.results[1].score > resp.results[2].score
        assert resp.results[0].document_name == "embed-test.pdf"
        assert resp.results[0].chunk_index == 0
        assert "embedding" not in resp.results[0].model_dump()

        # document filter
        resp_b = await semantic_search(
            "find me", top_k=10, document_id=doc_b, db=db_session
        )
        assert [r.content for r in resp_b.results] == ["farthest"]
        assert resp_b.results[0].document_id == doc_b

        # top_k bound
        resp_k = await semantic_search("find me", top_k=1, document_id=None, db=db_session)
        assert len(resp_k.results) == 1
        assert resp_k.results[0].content == "closest"

        # missing document filter -> empty results, no error
        resp_missing = await semantic_search(
            "find me", top_k=10, document_id=uuid.uuid4(), db=db_session
        )
        assert resp_missing.results == []
    finally:
        await _cleanup(db_session, [doc_a, doc_b])


async def test_semantic_search_ignores_stale_model_vectors(
    db_session: AsyncSession, monkeypatch
):
    doc_id = await _create_document(db_session)
    await _seed_chunk_with_vector(
        db_session, doc_id, 0, "old model chunk", _unit_vec(0),
        model_key="old-model@0",
    )

    async def fake_embed(texts):
        return [_unit_vec(0)]

    monkeypatch.setattr(embeddings, "embed_texts", fake_embed)

    try:
        resp = await semantic_search("q", top_k=10, document_id=None, db=db_session)
        assert resp.results == []
    finally:
        await _cleanup(db_session, [doc_id])


async def test_semantic_search_empty_results(db_session: AsyncSession, monkeypatch):
    async def fake_embed(texts):
        return [_unit_vec(0)]

    monkeypatch.setattr(embeddings, "embed_texts", fake_embed)

    resp = await semantic_search("nothing stored", top_k=5, document_id=None, db=db_session)
    assert resp.results == []
    assert resp.query == "nothing stored"


def test_search_request_validation():
    with pytest.raises(Exception):
        SearchRequest(query="   ")
    with pytest.raises(Exception):
        SearchRequest(query="x" * 4001)
    with pytest.raises(Exception):
        SearchRequest(query="ok", top_k=0)
    with pytest.raises(Exception):
        SearchRequest(query="ok", top_k=51)

    req = SearchRequest(query="  hello  ", top_k=5)
    assert req.query == "hello"
