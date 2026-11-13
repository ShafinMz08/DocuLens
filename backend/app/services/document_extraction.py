"""Isolated text extraction for stored documents.

Extracts plain text segments from PDF, DOCX and TXT files. This module is
intentionally independent of FastAPI, SQLAlchemy, PostgreSQL, Redis and the
API layer — it operates purely on filesystem paths.
"""

from dataclasses import dataclass
from pathlib import Path

from docx import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader


class ExtractionError(Exception):
    """Raised when a document cannot be parsed or yields no usable text."""


@dataclass(frozen=True)
class ExtractedSegment:
    text: str
    page_number: int | None


def _extract_pdf(file_path: Path) -> list[ExtractedSegment]:
    try:
        reader = PdfReader(str(file_path))
    except Exception as e:
        raise ExtractionError(f"Could not parse PDF document: {e}") from e

    segments: list[ExtractedSegment] = []
    try:
        page_count = len(reader.pages)
    except Exception as e:
        raise ExtractionError(f"Could not read PDF page tree: {e}") from e

    for index in range(page_count):
        try:
            text = reader.pages[index].extract_text() or ""
        except Exception as e:
            raise ExtractionError(
                f"Failed to extract text from PDF page {index + 1}"
            ) from e
        if text.strip():
            segments.append(ExtractedSegment(text=text, page_number=index + 1))

    if not segments:
        raise ExtractionError(
            "PDF contains no extractable text; scanned documents require OCR, "
            "which is not supported"
        )
    return segments


def _docx_block_items(document: DocxDocument):
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def _extract_docx(file_path: Path) -> list[ExtractedSegment]:
    try:
        document = DocxDocument(str(file_path))
    except Exception as e:
        raise ExtractionError(f"Could not parse DOCX document: {e}") from e

    segments: list[ExtractedSegment] = []
    for block in _docx_block_items(document):
        if isinstance(block, Paragraph):
            text = block.text
        else:
            rows = []
            for row in block.rows:
                cells = [cell.text.strip() for cell in row.cells]
                cells = [cell for cell in cells if cell]
                if cells:
                    rows.append(" | ".join(cells))
            text = "\n".join(rows)
        if text.strip():
            segments.append(ExtractedSegment(text=text, page_number=None))

    if not segments:
        raise ExtractionError("DOCX document contains no extractable text")
    return segments


def _extract_txt(file_path: Path) -> list[ExtractedSegment]:
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise ExtractionError("Text file is not valid UTF-8") from e
    except OSError as e:
        raise ExtractionError(f"Could not read text file: {e}") from e

    if not content.strip():
        raise ExtractionError("Text file is empty")
    return [ExtractedSegment(text=content, page_number=None)]


_EXTRACTORS = {
    ".pdf": _extract_pdf,
    ".docx": _extract_docx,
    ".txt": _extract_txt,
}


def extract_text(file_path: str | Path) -> list[ExtractedSegment]:
    """Extract text segments from a stored document.

    The format is determined by the file extension. Returns a list of
    ExtractedSegment ordered by document position; PDF segments carry 1-based
    page numbers, DOCX/TXT segments carry page_number=None.
    """
    path = Path(file_path)
    extractor = _EXTRACTORS.get(path.suffix.lower())
    if extractor is None:
        raise ExtractionError(f"Unsupported document format '{path.suffix}'")
    if not path.is_file():
        raise ExtractionError("Document file does not exist")
    return extractor(path)
