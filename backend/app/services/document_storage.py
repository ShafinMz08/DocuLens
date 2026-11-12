import os
import re
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile
from pypdf import PdfReader

from app.core.config import settings

CHUNK_SIZE = 1024 * 1024  # 1 MiB

ALLOWED_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
}

DOCX_REQUIRED_ENTRIES = {"[Content_Types].xml", "word/document.xml"}

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|]')


class UploadValidationError(ValueError):
    """Raised when an uploaded file fails validation."""


class FileTooLargeError(UploadValidationError):
    """Raised when an upload exceeds the configured size limit."""


@dataclass
class StoredUpload:
    original_filename: str
    stored_filename: str
    content_type: str
    file_size_bytes: int
    storage_path: str


def sanitize_original_filename(filename: str | None) -> str:
    name = (filename or "unnamed").replace("\\", "/")
    name = name.rsplit("/", 1)[-1]
    name = _CONTROL_CHARS.sub("", name)
    name = _UNSAFE_CHARS.sub("_", name).strip().lstrip(".")
    return name[:255] or "unnamed"


def validated_extension(filename: str | None) -> str:
    ext = Path(sanitize_original_filename(filename)).suffix.lower()
    if ext not in ALLOWED_TYPES:
        allowed = ", ".join(sorted(ALLOWED_TYPES))
        raise UploadValidationError(
            f"Unsupported file type '{ext or 'none'}'. Allowed: {allowed}"
        )
    return ext


def get_storage_dir() -> Path:
    path = Path(settings.DOCUMENT_STORAGE_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


async def stream_to_temp_file(
    upload: UploadFile, tmp_path: Path, max_bytes: int
) -> int:
    size = 0
    with open(tmp_path, "xb") as f:
        while chunk := await upload.read(CHUNK_SIZE):
            size += len(chunk)
            if size > max_bytes:
                raise FileTooLargeError(
                    f"File exceeds maximum size of {max_bytes} bytes"
                )
            f.write(chunk)
    return size


def _validate_pdf(file_path: Path) -> None:
    try:
        reader = PdfReader(str(file_path))
        if len(reader.pages) == 0:
            raise UploadValidationError("PDF contains no pages")
    except UploadValidationError:
        raise
    except Exception as e:
        raise UploadValidationError("File is not a valid PDF") from e


def validate_file_content(file_path: Path, ext: str) -> None:
    if ext == ".pdf":
        _validate_pdf(file_path)
    elif ext == ".docx":
        try:
            if not zipfile.is_zipfile(file_path):
                raise UploadValidationError("File is not a valid DOCX archive")
            with zipfile.ZipFile(file_path) as zf:
                entries = set(zf.namelist())
        except UploadValidationError:
            raise
        except (zipfile.BadZipFile, RuntimeError, OSError, EOFError) as e:
            raise UploadValidationError("File is not a valid DOCX archive") from e
        if not DOCX_REQUIRED_ENTRIES.issubset(entries):
            raise UploadValidationError("File is not a valid DOCX document")
    elif ext == ".txt":
        data = file_path.read_bytes()
        if b"\x00" in data:
            raise UploadValidationError("Text file contains binary content")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise UploadValidationError("Text file is not valid UTF-8") from e


async def store_uploaded_file(upload: UploadFile) -> StoredUpload:
    ext = validated_extension(upload.filename)
    content_type = ALLOWED_TYPES[ext]
    original_filename = sanitize_original_filename(upload.filename)
    max_bytes = settings.MAX_UPLOAD_SIZE_BYTES

    storage_dir = get_storage_dir()
    tmp_path = storage_dir / f".{uuid.uuid4().hex}.tmp"
    final_path: Path | None = None

    try:
        size = await stream_to_temp_file(upload, tmp_path, max_bytes)
        if size == 0:
            raise UploadValidationError("Uploaded file is empty")
        validate_file_content(tmp_path, ext)

        for _ in range(10):
            stored_filename = f"{uuid.uuid4().hex}{ext}"
            candidate_path = storage_dir / stored_filename
            try:
                os.link(tmp_path, candidate_path)
            except FileExistsError:
                continue
            final_path = candidate_path
            break
        if final_path is None:
            raise OSError("Could not allocate a unique stored filename")
        tmp_path.unlink()
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        if final_path is not None:
            final_path.unlink(missing_ok=True)
        raise

    return StoredUpload(
        original_filename=original_filename,
        stored_filename=stored_filename,
        content_type=content_type,
        file_size_bytes=size,
        storage_path=str(final_path),
    )
