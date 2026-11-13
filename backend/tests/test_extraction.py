import io

import pytest
from docx import Document as DocxDocument
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.services.document_extraction import ExtractionError, extract_text


def _pdf_content_stream(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1")


def make_pdf_bytes(page_texts: list[str]) -> bytes:
    writer = PdfWriter()
    for text in page_texts:
        page = writer.add_blank_page(width=612, height=792)

        font = DictionaryObject()
        font[NameObject("/Type")] = NameObject("/Font")
        font[NameObject("/Subtype")] = NameObject("/Type1")
        font[NameObject("/BaseFont")] = NameObject("/Helvetica")

        fonts = DictionaryObject()
        fonts[NameObject("/F1")] = font
        resources = DictionaryObject()
        resources[NameObject("/Font")] = fonts
        page[NameObject("/Resources")] = resources

        stream = DecodedStreamObject()
        stream.set_data(_pdf_content_stream(text))
        page[NameObject("/Contents")] = stream

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def make_docx_bytes() -> bytes:
    doc = DocxDocument()
    doc.add_paragraph("Introduction paragraph")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Name"
    table.cell(0, 1).text = "Value"
    table.cell(1, 0).text = "DocuLens"
    table.cell(1, 1).text = "AI"
    doc.add_paragraph("Closing paragraph")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_extract_pdf_text(tmp_path):
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(make_pdf_bytes(["Hello DocuLens", "Second page text"]))

    segments = extract_text(pdf_path)

    assert len(segments) == 2
    assert segments[0].page_number == 1
    assert "Hello DocuLens" in segments[0].text
    assert segments[1].page_number == 2
    assert "Second page text" in segments[1].text


def test_extract_pdf_skips_pages_without_text(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)  # page 1: no content

    page = writer.add_blank_page(width=612, height=792)  # page 2: text
    font = DictionaryObject()
    font[NameObject("/Type")] = NameObject("/Font")
    font[NameObject("/Subtype")] = NameObject("/Type1")
    font[NameObject("/BaseFont")] = NameObject("/Helvetica")
    fonts = DictionaryObject()
    fonts[NameObject("/F1")] = font
    resources = DictionaryObject()
    resources[NameObject("/Font")] = fonts
    page[NameObject("/Resources")] = resources
    stream = DecodedStreamObject()
    stream.set_data(_pdf_content_stream("Only real text"))
    page[NameObject("/Contents")] = stream

    buf = io.BytesIO()
    writer.write(buf)
    pdf_path = tmp_path / "mixed.pdf"
    pdf_path.write_bytes(buf.getvalue())

    segments = extract_text(pdf_path)

    assert len(segments) == 1
    assert segments[0].page_number == 2
    assert "Only real text" in segments[0].text


def test_extract_docx_text_preserves_order(tmp_path):
    docx_path = tmp_path / "doc.docx"
    docx_path.write_bytes(make_docx_bytes())

    segments = extract_text(docx_path)

    assert len(segments) == 3
    assert all(s.page_number is None for s in segments)
    assert "Introduction paragraph" in segments[0].text
    assert "Name" in segments[1].text
    assert "DocuLens" in segments[1].text
    assert "Closing paragraph" in segments[2].text


def test_docx_table_with_empty_cells(tmp_path):
    doc = DocxDocument()
    doc.add_paragraph("Before table")
    table = doc.add_table(rows=3, cols=3)
    # row 0: all cells empty -> should be dropped
    table.cell(1, 1).text = "Key"
    # row 2: meaningful content with empty cells interleaved
    table.cell(2, 0).text = "DocuLens"
    table.cell(2, 2).text = "AI"
    doc.add_paragraph("After table")

    docx_path = tmp_path / "sparse.docx"
    buf = io.BytesIO()
    doc.save(buf)
    docx_path.write_bytes(buf.getvalue())

    segments = extract_text(docx_path)

    assert [s.text for s in segments] == [
        "Before table",
        "Key\nDocuLens | AI",
        "After table",
    ]
    assert all(s.page_number is None for s in segments)


def test_extract_txt(tmp_path):
    txt_path = tmp_path / "notes.txt"
    txt_path.write_text("First line\nSecond line\n", encoding="utf-8")

    segments = extract_text(txt_path)

    assert len(segments) == 1
    assert segments[0].page_number is None
    assert segments[0].text == "First line\nSecond line\n"


def test_empty_text_raises(tmp_path):
    txt_path = tmp_path / "empty.txt"
    txt_path.write_text("   \n\t  ", encoding="utf-8")

    with pytest.raises(ExtractionError):
        extract_text(txt_path)


def test_unsupported_extension_raises(tmp_path):
    bad_path = tmp_path / "data.xyz"
    bad_path.write_bytes(b"whatever")

    with pytest.raises(ExtractionError, match="Unsupported"):
        extract_text(bad_path)


def test_malformed_pdf_raises(tmp_path):
    pdf_path = tmp_path / "broken.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nthis is not a real pdf")

    with pytest.raises(ExtractionError):
        extract_text(pdf_path)


def test_malformed_docx_raises(tmp_path):
    docx_path = tmp_path / "broken.docx"
    docx_path.write_bytes(b"not a zip archive")

    with pytest.raises(ExtractionError):
        extract_text(docx_path)


def test_malformed_txt_raises(tmp_path):
    txt_path = tmp_path / "binary.txt"
    txt_path.write_bytes(b"\xff\xfe\x00invalid utf-8")

    with pytest.raises(ExtractionError):
        extract_text(txt_path)


def test_pdf_page_extraction_failure_raises(tmp_path, monkeypatch):
    pdf_path = tmp_path / "partial.pdf"
    pdf_path.write_bytes(make_pdf_bytes(["Page one", "Page two"]))

    class FakePage:
        def __init__(self, should_fail):
            self._should_fail = should_fail

        def extract_text(self):
            if self._should_fail:
                raise RuntimeError("simulated page failure")
            return "Page one"

    class FakeReader:
        def __init__(self, *args, **kwargs):
            pass

        @property
        def pages(self):
            return [FakePage(False), FakePage(True)]

    monkeypatch.setattr(
        "app.services.document_extraction.PdfReader", FakeReader
    )

    with pytest.raises(ExtractionError, match="page 2") as excinfo:
        extract_text(pdf_path)
    assert isinstance(excinfo.value.__cause__, RuntimeError)


def test_pdf_without_extractable_text_raises(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    pdf_path = tmp_path / "scanned.pdf"
    pdf_path.write_bytes(buf.getvalue())

    with pytest.raises(ExtractionError, match="OCR"):
        extract_text(pdf_path)
