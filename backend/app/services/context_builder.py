import re
from dataclasses import dataclass

from app.core.config import settings


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    document_name: str
    chunk_index: int
    page_number: int | None
    content: str
    score: float


def deduplicate_chunks(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Drop exact chunk-id and content duplicates, preserving order."""
    seen_ids: set[str] = set()
    seen_content: set[str] = set()
    result = []
    for chunk in chunks:
        key = chunk.content.strip()
        if chunk.chunk_id in seen_ids or key in seen_content:
            continue
        seen_ids.add(chunk.chunk_id)
        seen_content.add(key)
        result.append(chunk)
    return result


def build_context(
    chunks: list[RetrievedChunk], max_chars: int | None = None
) -> tuple[str, list[RetrievedChunk]]:
    """Format retrieved chunks into a bounded prompt context.

    Chunks are emitted in the given (relevance) order until the character
    budget is exhausted. Returns the context text and the chunks actually
    included, so citations only reference material sent to the model.
    """
    max_chars = max_chars or settings.RAG_MAX_CONTEXT_CHARS
    chunks = deduplicate_chunks(chunks)

    blocks: list[str] = []
    included: list[RetrievedChunk] = []
    used = 0

    for i, chunk in enumerate(chunks, start=1):
        page = chunk.page_number if chunk.page_number is not None else "n/a"
        header = (
            f"[Source {i}] Document: {chunk.document_name} | "
            f"Page: {page} | Chunk: {chunk.chunk_index}"
        )
        block = f"{header}\n{chunk.content}"

        if used + len(block) + 2 > max_chars and included:
            break
        if used + len(block) + 2 > max_chars:
            # first chunk alone exceeds the budget: truncate its content
            room = max(0, max_chars - used - len(header) - 2)
            block = f"{header}\n{chunk.content[:room]}"
        blocks.append(block)
        included.append(chunk)
        used += len(block) + 2

    return "\n\n".join(blocks), included


_CITATION_RE = re.compile(r"\[(\d+)\]")


def extract_citation_indices(answer: str) -> list[int]:
    """Return unique 1-based source indices cited in the answer, in order."""
    seen: set[int] = set()
    indices = []
    for match in _CITATION_RE.finditer(answer):
        idx = int(match.group(1))
        if idx not in seen:
            seen.add(idx)
            indices.append(idx)
    return indices
