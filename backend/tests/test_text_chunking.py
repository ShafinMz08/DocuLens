from app.services.document_extraction import ExtractedSegment
from app.services.text_chunking import chunk_segments


def make_text(word: str = "lorem", count: int = 400) -> str:
    return " ".join([word] * count)


def test_short_document_produces_one_chunk():
    segments = [ExtractedSegment(text="Short document text.", page_number=None)]
    chunks = chunk_segments(segments)

    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].text == "Short document text."
    assert chunks[0].page_number is None


def test_long_document_produces_multiple_chunks():
    segments = [ExtractedSegment(text=make_text(count=600), page_number=None)]
    chunks = chunk_segments(segments)

    assert len(chunks) > 1
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert all(len(c.text) <= 1000 for c in chunks)
    assert all(c.text.strip() for c in chunks)


def test_max_chunk_size_respected():
    # ~120 chars per "word " unit -> forces several windows
    text = " ".join(f"w{i:03d}" for i in range(300))
    segments = [ExtractedSegment(text=text, page_number=None)]
    chunks = chunk_segments(segments)

    assert len(chunks) > 1
    assert all(len(c.text) <= 1000 for c in chunks)


def test_overlap_is_preserved():
    text = make_text(count=600)
    segments = [ExtractedSegment(text=text, page_number=None)]
    chunks = chunk_segments(segments)

    assert len(chunks) > 1
    for prev, nxt in zip(chunks, chunks[1:]):
        # the head of the next chunk comes from the tail of the previous one
        assert nxt.text[:80] in prev.text


def test_splits_prefer_word_boundaries():
    words = [f"word{i}" for i in range(400)]
    text = " ".join(words)
    segments = [ExtractedSegment(text=text, page_number=None)]
    chunks = chunk_segments(segments)

    word_set = set(words)
    for chunk in chunks:
        # last token of every chunk must be a complete source word
        assert chunk.text.split()[-1] in word_set


def test_empty_and_whitespace_input():
    assert chunk_segments([]) == []
    assert chunk_segments([ExtractedSegment(text="   \n\t  ", page_number=None)]) == []

    chunks = chunk_segments(
        [
            ExtractedSegment(text="   ", page_number=None),
            ExtractedSegment(text="real content", page_number=None),
        ]
    )
    assert len(chunks) == 1
    assert chunks[0].text == "real content"


def test_pdf_page_boundaries_preserved():
    page1 = "alpha " * 200  # ~1200 chars -> multiple chunks on page 1
    page2 = "beta " * 50
    segments = [
        ExtractedSegment(text=page1, page_number=1),
        ExtractedSegment(text=page2, page_number=2),
    ]
    chunks = chunk_segments(segments)

    page1_chunks = [c for c in chunks if c.page_number == 1]
    page2_chunks = [c for c in chunks if c.page_number == 2]

    assert len(page1_chunks) > 1
    assert len(page2_chunks) == 1
    assert all("beta" not in c.text for c in page1_chunks)
    assert all("alpha" not in c.text for c in page2_chunks)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_none_page_segments_combined_in_order():
    segments = [
        ExtractedSegment(text="First part. ", page_number=None),
        ExtractedSegment(text="Second part. ", page_number=None),
        ExtractedSegment(text="Third part.", page_number=None),
    ]
    chunks = chunk_segments(segments)

    assert len(chunks) == 1
    text = chunks[0].text
    assert text.index("First part") < text.index("Second part") < text.index(
        "Third part"
    )


def test_chunk_indexes_sequential_across_streams():
    segments = [
        ExtractedSegment(text="a" * 1500, page_number=1),
        ExtractedSegment(text="b" * 1500, page_number=2),
        ExtractedSegment(text="tail", page_number=None),
    ]
    chunks = chunk_segments(segments)

    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert chunks[-1].page_number is None
    assert chunks[-1].text == "tail"


def test_long_unbroken_word_respects_max_size():
    segments = [ExtractedSegment(text="x" * 2500, page_number=None)]
    chunks = chunk_segments(segments)

    assert len(chunks) >= 3
    assert all(len(c.text) <= 1000 for c in chunks)
    assert "".join(c.text for c in chunks).replace("x", "") == ""


def test_boundary_too_close_to_overlap_uses_hard_split():
    # The only whitespace in the first window sits at index 151 — just past
    # the 150-char overlap. Accepting it would advance pos by ~1 char and
    # produce a degenerate ~150-char chunk; the splitter must hard-split.
    text = "a" * 151 + " " + "b" * 848 + " " + "c" * 2000
    chunks = chunk_segments([ExtractedSegment(text=text, page_number=None)])

    assert len(chunks) <= 4
    assert all(len(c.text) <= 1000 for c in chunks)
    assert all(len(c.text) > 500 for c in chunks[:-1])


def test_no_infinite_loop_or_empty_chunks():
    # pathological mix: giant word, whitespace run, normal text
    segments = [
        ExtractedSegment(text="y" * 5000 + " " * 2000 + make_text(count=100), page_number=None)
    ]
    chunks = chunk_segments(segments)

    assert len(chunks) > 0
    assert all(c.text for c in chunks)
    assert all(len(c.text) <= 1000 for c in chunks)
