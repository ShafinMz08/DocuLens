import asyncio
import threading
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logger import logger
from app.models import (
    Document,
    DocumentChunk,
    DocumentStatus,
    EmbeddingStatus,
)
from app.schemas.search import EmbeddingResult, SearchResponse, SearchResultItem
from app.services.document_processing import DocumentNotFoundError


class EmbeddingNotReadyError(Exception):
    pass


class EmbeddingConflictError(Exception):
    pass


class EmbeddingError(Exception):
    """Embedding failed. Carries best-effort persisted chunk counts so
    callers can report partial progress accurately."""

    def __init__(
        self,
        message: str,
        *,
        embedded_chunks: int | None = None,
        total_chunks: int | None = None,
        skipped_chunks: int | None = None,
    ):
        super().__init__(message)
        self.embedded_chunks = embedded_chunks
        self.total_chunks = total_chunks
        self.skipped_chunks = skipped_chunks


_model = None
_model_lock = threading.Lock()


def embedding_model_key() -> str:
    return f"{settings.EMBEDDING_MODEL_NAME}@{settings.EMBEDDING_MODEL_VERSION}"


def _load_model():
    """Load the FastEmbed model once and reuse it (runs in a worker thread)."""
    global _model
    with _model_lock:
        if _model is None:
            from fastembed import TextEmbedding

            _model = TextEmbedding(
                model_name=settings.EMBEDDING_MODEL_NAME,
                cache_dir=settings.FASTEMBED_CACHE_DIR,
            )
    return _model


def _embed_texts_sync(texts: list[str]) -> list[list[float]]:
    model = _load_model()
    return [vec.tolist() for vec in model.embed(texts)]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    return await asyncio.to_thread(_embed_texts_sync, texts)


def _embedding_is_stale(started_at: datetime | None) -> bool:
    if started_at is None:
        return True
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - started_at > timedelta(
        seconds=settings.EMBEDDING_STALE_SECONDS
    )


async def _pending_chunks(
    db: AsyncSession, document_id: uuid.UUID, model_key: str
) -> list[tuple[uuid.UUID, str]]:
    result = await db.execute(
        select(DocumentChunk.id, DocumentChunk.content)
        .where(
            DocumentChunk.document_id == document_id,
            func.length(func.trim(DocumentChunk.content)) > 0,
            or_(
                DocumentChunk.embedding.is_(None),
                DocumentChunk.embedding_model != model_key,
            ),
        )
        .order_by(DocumentChunk.chunk_index)
    )
    return [(row.id, row.content) for row in result.all()]


async def _chunk_counts(
    db: AsyncSession, document_id: uuid.UUID, model_key: str
) -> tuple[int, int, int]:
    result = await db.execute(
        select(
            func.count().label("total"),
            func.count()
            .filter(
                DocumentChunk.embedding_model == model_key,
                DocumentChunk.embedding.isnot(None),
            )
            .label("embedded"),
            func.count()
            .filter(func.length(func.trim(DocumentChunk.content)) == 0)
            .label("skipped"),
        ).where(DocumentChunk.document_id == document_id)
    )
    row = result.one()
    return row.total, row.embedded, row.skipped


async def _fail_embedding(
    db: AsyncSession, document_id: uuid.UUID, message: str
) -> None:
    await db.rollback()
    await db.execute(
        update(Document)
        .where(Document.id == document_id)
        .values(
            embedding_status=EmbeddingStatus.FAILED,
            embedding_error=message[:2000],
        )
    )
    await db.commit()


async def embed_document(document_id: uuid.UUID, db: AsyncSession):
    """Generate embeddings for all embeddable chunks of a document.

    Stage A locks the document row and marks embedding as PROCESSING.
    Stage B embeds pending chunks in batches (CPU inference runs in a
    threadpool), committing each batch separately so a failure never marks
    the whole document embedded. A PROCESSING state older than
    EMBEDDING_STALE_SECONDS is treated as interrupted and may be retried.
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
    if document.status != DocumentStatus.COMPLETED:
        raise EmbeddingNotReadyError(
            "Document must be processed successfully before embedding"
        )
    if (
        document.embedding_status == EmbeddingStatus.PROCESSING
        and not _embedding_is_stale(document.embedding_started_at)
    ):
        raise EmbeddingConflictError("Document is already being embedded")

    model_key = embedding_model_key()
    document.embedding_status = EmbeddingStatus.PROCESSING
    document.embedding_error = None
    document.embedding_started_at = datetime.now(timezone.utc)
    await db.commit()

    try:
        pending = await _pending_chunks(db, document_id, model_key)

        for i in range(0, len(pending), settings.EMBEDDING_BATCH_SIZE):
            batch = pending[i : i + settings.EMBEDDING_BATCH_SIZE]
            texts = [content for _, content in batch]
            vectors = await embed_texts(texts)

            for (chunk_id, _), vector in zip(batch, vectors):
                await db.execute(
                    update(DocumentChunk)
                    .where(DocumentChunk.id == chunk_id)
                    .values(embedding=vector, embedding_model=model_key)
                )
            await db.commit()

        total, embedded, skipped = await _chunk_counts(db, document_id, model_key)

        document.embedding_status = EmbeddingStatus.COMPLETED
        document.embedded_at = datetime.now(timezone.utc)
        await db.commit()
    except Exception as e:
        message = f"{type(e).__name__}: {e}"
        logger.error(
            "Embedding failed for document %s: %s", document_id, message
        )
        await _fail_embedding(db, document_id, message)
        try:
            total, embedded, skipped = await _chunk_counts(
                db, document_id, model_key
            )
        except Exception:
            total = embedded = skipped = None
        raise EmbeddingError(
            message,
            embedded_chunks=embedded,
            total_chunks=total,
            skipped_chunks=skipped,
        ) from e

    return EmbeddingResult(
        document_id=document_id,
        embedding_status=EmbeddingStatus.COMPLETED,
        embedding_model=model_key,
        total_chunks=total,
        embedded_chunks=embedded,
        skipped_chunks=skipped,
        error_message=None,
    )


_SEARCH_SQL = """
SELECT
    c.id AS chunk_id,
    c.document_id,
    d.original_filename,
    c.chunk_index,
    c.page_number,
    c.content,
    c.embedding <=> CAST(:query_vector AS vector) AS distance
FROM document_chunks c
JOIN documents d ON d.id = c.document_id
WHERE c.embedding IS NOT NULL
  AND c.embedding_model = :model_key
  AND (CAST(:document_id AS uuid) IS NULL OR c.document_id = CAST(:document_id AS uuid))
ORDER BY distance ASC
LIMIT :top_k
"""


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in vector) + "]"


async def semantic_search(
    query: str,
    top_k: int,
    document_id: uuid.UUID | None,
    db: AsyncSession,
):
    """Embed a natural-language query and return nearest chunks by cosine
    similarity. Only chunks embedded with the currently configured model
    are searched."""
    query = query.strip()
    if not query:
        return SearchResponse(query=query, results=[])

    vectors = await embed_texts([query])
    query_vector = _vector_literal(vectors[0])

    result = await db.execute(
        text(_SEARCH_SQL),
        {
            "query_vector": query_vector,
            "model_key": embedding_model_key(),
            "document_id": document_id,
            "top_k": top_k,
        },
    )
    rows = result.all()

    return SearchResponse(
        query=query,
        results=[
            SearchResultItem(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                document_name=row.original_filename,
                chunk_index=row.chunk_index,
                page_number=row.page_number,
                content=row.content,
                score=round(max(0.0, 1.0 - float(row.distance)), 6),
            )
            for row in rows
        ],
    )
