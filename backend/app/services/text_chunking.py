"""Standalone chunking of extracted text segments.

Accepts ExtractedSegment objects produced by document_extraction and splits
them into fixed-size text chunks. This module is intentionally independent of
FastAPI, SQLAlchemy, PostgreSQL, Redis and the API layer.
"""

from dataclasses import dataclass

from app.services.document_extraction import ExtractedSegment

DEFAULT_MAX_CHUNK_SIZE = 1000
DEFAULT_OVERLAP = 150

_WHITESPACE = " \t\n\r\f\v"


@dataclass(frozen=True)
class TextChunk:
    chunk_index: int
    text: str
    page_number: int | None


def _group_streams(
    segments: list[ExtractedSegment],
) -> list[tuple[int | None, str]]:
    """Group segments into chunkable text streams.

    Each paged segment becomes its own stream so text from different PDF pages
    is never combined. Consecutive page-less segments (DOCX/TXT) are joined
    into a single stream in document order.
    """
    streams: list[tuple[int | None, str]] = []
    pending: list[str] = []

    def flush_pending() -> None:
        if pending:
            streams.append((None, "\n".join(pending)))
            pending.clear()

    for segment in segments:
        if segment.page_number is None:
            pending.append(segment.text)
        else:
            flush_pending()
            streams.append((segment.page_number, segment.text))
    flush_pending()
    return streams


def _last_whitespace_index(window: str) -> int:
    idx = -1
    for char in _WHITESPACE:
        found = window.rfind(char)
        if found > idx:
            idx = found
    return idx


def _split_text(text: str, max_size: int, overlap: int) -> list[str]:
    """Split text into chunks of at most max_size chars.

    Prefers the last word boundary inside each window; falls back to a hard
    split when no usable boundary exists (e.g. a single very long word).
    Each new chunk overlaps the previous one by roughly `overlap` chars.
    """
    text = text.strip()
    if not text:
        return []

    chunks: list[str] = []
    pos = 0
    total = len(text)

    while pos < total:
        end = pos + max_size
        if end >= total:
            tail = text[pos:].strip()
            if tail:
                chunks.append(tail)
            break

        window = text[pos:end]
        ws_idx = _last_whitespace_index(window)
        # A boundary only helps if it yields meaningful forward progress;
        # a break barely past the overlap would rescan nearly the same window,
        # so fall back to a hard split (e.g. inside a very long word).
        min_progress = max_size // 2
        cut = (
            ws_idx
            if ws_idx > overlap and ws_idx - overlap >= min_progress
            else max_size
        )

        chunk_text = text[pos : pos + cut].strip()
        if chunk_text:
            chunks.append(chunk_text)
        pos += cut - overlap

    return chunks


def chunk_segments(
    segments: list[ExtractedSegment],
    max_chunk_size: int = DEFAULT_MAX_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[TextChunk]:
    """Chunk extracted segments into TextChunk objects.

    Chunk indexes start at 0 and increase sequentially across the whole
    document. PDF page numbers are preserved per chunk; page-less streams
    produce chunks with page_number=None.
    """
    if overlap < 0 or overlap >= max_chunk_size:
        raise ValueError("overlap must be >= 0 and smaller than max_chunk_size")

    chunks: list[TextChunk] = []
    for page_number, text in _group_streams(segments):
        for piece in _split_text(text, max_chunk_size, overlap):
            chunks.append(
                TextChunk(
                    chunk_index=len(chunks),
                    text=piece,
                    page_number=page_number,
                )
            )
    return chunks
