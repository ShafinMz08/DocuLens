from app.core.config import settings
from app.services.context_builder import (
    RetrievedChunk,
    build_context,
    deduplicate_chunks,
    extract_citation_indices,
)


def _chunk(i, content=None, page=None, name="doc.pdf", score=0.9):
    return RetrievedChunk(
        chunk_id=f"chunk-{i}",
        document_id="doc-1",
        document_name=name,
        chunk_index=i,
        page_number=page,
        content=content or f"content of chunk {i} " * 5,
        score=score,
    )


def test_deduplicate_by_id_and_content():
    a = _chunk(0, content="same text")
    b = _chunk(1, content="same text")  # same content, different id
    c = RetrievedChunk(**{**a.__dict__, "chunk_id": "chunk-0b"})
    d = _chunk(2, content="different")

    result = deduplicate_chunks([a, b, c, d])
    # a kept; b dropped (same content); c dropped? c has same content too -> dropped; d kept
    assert [r.chunk_id for r in result] == ["chunk-0", "chunk-2"]


def test_build_context_preserves_metadata():
    chunks = [_chunk(0, page=3, name="report.pdf")]
    context, included = build_context(chunks)

    assert "[Source 1]" in context
    assert "Document: report.pdf" in context
    assert "Page: 3" in context
    assert "Chunk: 0" in context
    assert "content of chunk 0" in context
    assert included == chunks


def test_build_context_page_none():
    context, _ = build_context([_chunk(0, page=None)])
    assert "Page: n/a" in context


def test_build_context_budget():
    big = "x" * 5000
    chunks = [_chunk(i, content=big) for i in range(5)]
    context, included = build_context(chunks, max_chars=6000)

    assert len(context) <= 6100
    assert 0 < len(included) < 5
    # sources numbered contiguously for included chunks only
    assert "[Source 1]" in context
    assert f"[Source {len(included)}]" in context
    assert f"[Source {len(included) + 1}]" not in context


def test_build_context_first_chunk_truncated():
    huge = "y" * 20000
    context, included = build_context([_chunk(0, content=huge)], max_chars=1000)
    assert len(included) == 1
    assert len(context) <= 1000


def test_build_context_empty():
    context, included = build_context([])
    assert context == ""
    assert included == []


def test_extract_citation_indices():
    assert extract_citation_indices("Answer [1] and more [2]. See [1] again.") == [1, 2]
    assert extract_citation_indices("no citations here") == []
    assert extract_citation_indices("[10] out of range") == [10]
