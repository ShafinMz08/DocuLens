import io
import re
import uuid
import zipfile
from datetime import datetime
from types import SimpleNamespace
from sqlalchemy.engine import make_url

import httpx
import pytest_asyncio
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models import Document, DocumentChunk, DocumentStatus
from app.services import embeddings
from tests.test_extraction import make_pdf_bytes as _make_pdf_with_text


def make_pdf_bytes() -> bytes:
    return _make_pdf_with_text(["Test document content for processing"])


PDF_BYTES = make_pdf_bytes()
TXT_BYTES = "Hello DocuLens\n".encode("utf-8")


def make_docx_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        zf.writestr("word/document.xml", "<w:document/>")
    return buf.getvalue()


def make_zip_bytes(*names: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in names:
            zf.writestr(name, "content")
    return buf.getvalue()




@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch):
    storage_dir = tmp_path / "documents"
    monkeypatch.setattr(settings, "DOCUMENT_STORAGE_DIR", str(storage_dir))

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

    async def override_get_db():
        async with factory() as session:
            yield session

    # deterministic embeddings for every test in this module so /process
    # never downloads or runs the real FastEmbed model
    monkeypatch.setattr(embeddings, "embed_texts", _fake_embedder())

    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db

    test_env = SimpleNamespace(
        client=None,
        storage_dir=storage_dir,
        doc_ids=[],
        factory=factory,
        get_db_override=override_get_db,
    )

    try:
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            test_env.client = client
            yield test_env

    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)

        try:
            if test_env.doc_ids:
                async with factory() as session:
                    await session.execute(
                        delete(Document).where(
                            Document.id.in_(test_env.doc_ids)
                        )
                    )
                    await session.commit()
        finally:
            await engine.dispose()

async def upload(client: httpx.AsyncClient, filename: str, content: bytes):
    return await client.post(
        "/api/v1/documents/upload",
        files={"file": (filename, content, "application/octet-stream")},
    )


def track(env, response) -> dict:
    data = response.json()
    env.doc_ids.append(uuid.UUID(data["id"]))
    return data


async def test_upload_pdf_success(env):
    response = await upload(env.client, "test-report.pdf", PDF_BYTES)
    assert response.status_code == 201
    data = track(env, response)

    assert data["original_filename"] == "test-report.pdf"
    assert data["content_type"] == "application/pdf"
    assert data["file_size_bytes"] == len(PDF_BYTES)
    assert data["status"] == "uploaded"
    assert "storage_path" not in data
    assert "stored_filename" not in data

    files = list(env.storage_dir.glob("*.pdf"))
    assert len(files) == 1
    assert re.fullmatch(r"[0-9a-f]{32}\.pdf", files[0].name)
    assert files[0].read_bytes() == PDF_BYTES


async def test_upload_docx_success(env):
    response = await upload(env.client, "test-doc.docx", make_docx_bytes())
    assert response.status_code == 201
    data = track(env, response)
    assert data["content_type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert data["status"] == "uploaded"
    assert len(list(env.storage_dir.glob("*.docx"))) == 1


async def test_upload_txt_success(env):
    response = await upload(env.client, "test-notes.txt", TXT_BYTES)
    assert response.status_code == 201
    data = track(env, response)
    assert data["content_type"] == "text/plain"
    assert data["file_size_bytes"] == len(TXT_BYTES)
    assert len(list(env.storage_dir.glob("*.txt"))) == 1


async def test_metadata_persisted_in_database(env):
    response = await upload(env.client, "test-meta.pdf", PDF_BYTES)
    assert response.status_code == 201
    data = track(env, response)

    async with env.factory() as session:
        doc = await session.scalar(
            select(Document).where(Document.id == uuid.UUID(data["id"]))
        )
        assert doc is not None
        assert doc.original_filename == "test-meta.pdf"
        assert doc.stored_filename.endswith(".pdf")
        assert doc.content_type == "application/pdf"
        assert doc.file_size_bytes == len(PDF_BYTES)
        assert doc.status == DocumentStatus.UPLOADED
        assert doc.storage_path.startswith(str(env.storage_dir))
        assert (env.storage_dir / doc.stored_filename).exists()


async def test_list_documents_and_pagination(env):
    async with env.factory() as session:
        baseline = (
            await session.scalar(select(func.count()).select_from(Document)) or 0
        )

    ids = []
    for name in ("test-a.pdf", "test-b.pdf", "test-c.pdf"):
        response = await upload(env.client, name, PDF_BYTES)
        assert response.status_code == 201
        ids.append(track(env, response)["id"])

    response = await env.client.get("/api/v1/documents?limit=100")
    assert response.status_code == 200
    listing = response.json()
    assert listing["total"] == baseline + 3
    assert listing["limit"] == 100

    items = listing["items"]
    keys = [(datetime.fromisoformat(i["created_at"]), i["id"]) for i in items]
    assert keys == sorted(keys, key=lambda k: (k[0], k[1]), reverse=True)

    our_ids = set(ids)
    ours = [i for i in items if i["id"] in our_ids]
    assert len(ours) == 3
    for item in ours:
        assert "storage_path" not in item
        assert "stored_filename" not in item

    expected_order = [i["id"] for i in items]

    response = await env.client.get("/api/v1/documents?limit=2")
    page1 = response.json()
    assert page1["total"] == baseline + 3
    assert page1["skip"] == 0
    assert page1["limit"] == 2
    assert [i["id"] for i in page1["items"]] == expected_order[:2]

    response = await env.client.get("/api/v1/documents?skip=2&limit=2")
    page2 = response.json()
    assert page2["total"] == baseline + 3
    assert page2["skip"] == 2
    assert [i["id"] for i in page2["items"]] == expected_order[2:4]

    response = await env.client.get("/api/v1/documents?limit=0")
    assert response.status_code == 422
    response = await env.client.get("/api/v1/documents?limit=101")
    assert response.status_code == 422


async def test_unsupported_extension_rejected(env):
    response = await upload(env.client, "test-evil.exe", b"MZ\x90\x00")
    assert response.status_code == 400
    assert not env.storage_dir.exists() or list(env.storage_dir.iterdir()) == []


async def test_empty_file_rejected(env):
    response = await upload(env.client, "test-empty.txt", b"")
    assert response.status_code == 400


async def test_oversized_upload_rejected(env, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_BYTES", 8)
    response = await upload(env.client, "test-big.txt", TXT_BYTES)

    if response.status_code == 201:
        track(env, response)

    assert response.status_code == 413


async def test_invalid_pdf_rejected(env):
    response = await upload(env.client, "test-fake.pdf", b"this is not a pdf")
    assert response.status_code == 400

    response = await upload(
        env.client, "test-badstruct.pdf", b"%PDF-1.4\nthis is not a real pdf"
    )
    assert response.status_code == 400


async def test_invalid_docx_rejected(env):
    response = await upload(env.client, "test-fake.docx", b"not a zip archive")
    assert response.status_code == 400

    not_docx = make_zip_bytes("readme.txt")
    response = await upload(env.client, "test-notdocx.docx", not_docx)
    assert response.status_code == 400


async def test_invalid_txt_rejected(env):
    response = await upload(env.client, "test-binary.txt", b"\xff\xfe\x00binary")
    assert response.status_code == 400


async def test_database_failure_cleans_up_file(env):
    class FailingSession:
        def add(self, obj):
            pass

        async def commit(self):
            raise RuntimeError("simulated database failure")

        async def rollback(self):
            pass

    async def failing_get_db():
        yield FailingSession()

    app.dependency_overrides[get_db] = failing_get_db
    try:
        response = await upload(env.client, "test-dbfail.pdf", PDF_BYTES)
        assert response.status_code == 500
    finally:
        app.dependency_overrides[get_db] = env.get_db_override

    if env.storage_dir.exists():
        assert list(env.storage_dir.iterdir()) == []


async def test_original_filename_path_traversal_safe(env):
    response = await upload(
        env.client, "../../test-evil/../test-traversal.pdf", PDF_BYTES
    )
    assert response.status_code == 201
    data = track(env, response)

    assert data["original_filename"] == "test-traversal.pdf"
    assert ".." not in data["original_filename"]
    assert "/" not in data["original_filename"]
    assert "\\" not in data["original_filename"]

    files = list(env.storage_dir.glob("*.pdf"))
    assert len(files) == 1
    assert files[0].parent == env.storage_dir


async def test_process_document_success(env):
    response = await upload(env.client, "test-process.pdf", PDF_BYTES)
    assert response.status_code == 201
    data = track(env, response)

    response = await env.client.post(f"/api/v1/documents/{data['id']}/process")
    assert response.status_code == 200
    result = response.json()
    assert result["document_id"] == data["id"]
    assert result["document_status"] == "completed"
    assert result["attempt_number"] == 1
    assert result["processing_status"] == "completed"
    assert result["chunks_created"] >= 1
    assert result["error_message"] is None
    # /process now embeds automatically
    assert result["embedding_status"] == "completed"
    assert result["embedded_chunks"] == result["chunks_created"]
    assert result["total_chunks"] == result["chunks_created"]
    assert result["skipped_chunks"] == 0
    assert result["embedding_error"] is None


async def test_process_missing_document_404(env):
    response = await env.client.post(f"/api/v1/documents/{uuid.uuid4()}/process")
    assert response.status_code == 404


async def test_process_completed_document_409(env):
    response = await upload(env.client, "test-twice.pdf", PDF_BYTES)
    assert response.status_code == 201
    data = track(env, response)

    response = await env.client.post(f"/api/v1/documents/{data['id']}/process")
    assert response.status_code == 200

    response = await env.client.post(f"/api/v1/documents/{data['id']}/process")
    assert response.status_code == 409


async def test_process_already_processing_409(env):
    response = await upload(env.client, "test-busy.pdf", PDF_BYTES)
    assert response.status_code == 201
    data = track(env, response)

    async with env.factory() as session:
        await session.execute(
            update(Document)
            .where(Document.id == uuid.UUID(data["id"]))
            .values(status=DocumentStatus.PROCESSING)
        )
        await session.commit()

    response = await env.client.post(f"/api/v1/documents/{data['id']}/process")
    assert response.status_code == 409


def _fake_embedder():
    async def fake(texts):
        vecs = []
        for i, _ in enumerate(texts):
            vec = [0.0] * settings.EMBEDDING_DIMENSIONS
            vec[i % settings.EMBEDDING_DIMENSIONS] = 1.0
            vecs.append(vec)
        return vecs

    return fake


async def _processed_document(env, monkeypatch, filename="test-embed.pdf"):
    monkeypatch.setattr(embeddings, "embed_texts", _fake_embedder())
    response = await upload(env.client, filename, PDF_BYTES)
    assert response.status_code == 201
    data = track(env, response)

    response = await env.client.post(f"/api/v1/documents/{data['id']}/process")
    assert response.status_code == 200
    return data


async def test_embed_document_success(env, monkeypatch):
    data = await _processed_document(env, monkeypatch)

    response = await env.client.post(f"/api/v1/documents/{data['id']}/embed")
    assert response.status_code == 200
    result = response.json()
    assert result["document_id"] == data["id"]
    assert result["embedding_status"] == "completed"
    assert result["embedding_model"].endswith("@1")
    assert result["total_chunks"] >= 1
    assert result["embedded_chunks"] == result["total_chunks"]
    assert result["skipped_chunks"] == 0
    assert result["error_message"] is None

    # repeat request is safe and idempotent
    response = await env.client.post(f"/api/v1/documents/{data['id']}/embed")
    assert response.status_code == 200
    assert response.json()["embedding_status"] == "completed"


async def test_embed_missing_document_404(env):
    response = await env.client.post(f"/api/v1/documents/{uuid.uuid4()}/embed")
    assert response.status_code == 404


async def test_embed_unprocessed_document_409(env):
    response = await upload(env.client, "test-notprocessed.pdf", PDF_BYTES)
    assert response.status_code == 201
    data = track(env, response)

    response = await env.client.post(f"/api/v1/documents/{data['id']}/embed")
    assert response.status_code == 409


async def test_process_embedding_failure_keeps_chunks_and_retry(
    env, monkeypatch
):
    async def boom(_texts):
        raise RuntimeError("model failure")

    # embedding fails during the automatic post-processing embed
    monkeypatch.setattr(embeddings, "embed_texts", boom)

    response = await upload(env.client, "test-autoembed.pdf", PDF_BYTES)
    assert response.status_code == 201
    data = track(env, response)

    response = await env.client.post(f"/api/v1/documents/{data['id']}/process")
    assert response.status_code == 200
    result = response.json()

    # extraction succeeded; only embedding failed
    assert result["document_status"] == "completed"
    assert result["processing_status"] == "completed"
    assert result["chunks_created"] >= 1
    assert result["embedding_status"] == "failed"
    assert result["embedded_chunks"] == 0
    assert result["total_chunks"] == result["chunks_created"]
    assert result["embedding_error"]
    assert "model failure" not in result["embedding_error"]

    # chunks were persisted despite the embedding failure
    async with env.factory() as session:
        doc = await session.scalar(
            select(Document).where(Document.id == uuid.UUID(data["id"]))
        )
        assert doc.status == DocumentStatus.COMPLETED
        assert doc.embedding_status.value == "failed"
        chunks = (
            await session.execute(
                select(DocumentChunk).where(
                    DocumentChunk.document_id == doc.id
                )
            )
        ).scalars().all()
        assert len(chunks) == result["chunks_created"]

    # retry through /embed succeeds without reprocessing
    monkeypatch.setattr(embeddings, "embed_texts", _fake_embedder())
    response = await env.client.post(f"/api/v1/documents/{data['id']}/embed")
    assert response.status_code == 200
    retry = response.json()
    assert retry["embedding_status"] == "completed"
    assert retry["embedded_chunks"] == result["chunks_created"]

    async with env.factory() as session:
        doc = await session.scalar(
            select(Document).where(Document.id == uuid.UUID(data["id"]))
        )
        assert doc.embedding_status.value == "completed"
        assert doc.embedding_error is None


async def test_embed_failure_returns_500(env, monkeypatch):
    async def boom(_texts):
        raise RuntimeError("model failure")

    # make the automatic embedding fail during /process first
    monkeypatch.setattr(embeddings, "embed_texts", boom)
    response = await upload(env.client, "test-embedfail.pdf", PDF_BYTES)
    assert response.status_code == 201
    data = track(env, response)
    response = await env.client.post(f"/api/v1/documents/{data['id']}/process")
    assert response.status_code == 200

    # /embed retries and fails -> 500 without leaking internals
    response = await env.client.post(f"/api/v1/documents/{data['id']}/embed")
    assert response.status_code == 500
    assert "model failure" not in response.text

    async with env.factory() as session:
        doc = await session.scalar(
            select(Document).where(Document.id == uuid.UUID(data["id"]))
        )
        assert doc.embedding_status.value == "failed"
        assert "model failure" in doc.embedding_error


async def test_semantic_search_endpoint(env, monkeypatch):
    data = await _processed_document(env, monkeypatch, "test-search.pdf")

    response = await env.client.post(f"/api/v1/documents/{data['id']}/embed")
    assert response.status_code == 200

    async def query_embed(texts):
        vec = [0.0] * settings.EMBEDDING_DIMENSIONS
        vec[0] = 1.0
        return [vec for _ in texts]

    monkeypatch.setattr(embeddings, "embed_texts", query_embed)

    response = await env.client.post(
        "/api/v1/search", json={"query": "test document content", "top_k": 5}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "test document content"
    assert len(payload["results"]) >= 1
    first = payload["results"][0]
    assert first["document_id"] == data["id"]
    assert first["document_name"] == "test-search.pdf"
    assert "content" in first
    assert "score" in first
    assert "embedding" not in first

    scores = [r["score"] for r in payload["results"]]
    assert scores == sorted(scores, reverse=True)


async def test_semantic_search_document_filter(env, monkeypatch):
    data_a = await _processed_document(env, monkeypatch, "test-sa.pdf")
    data_b = await _processed_document(env, monkeypatch, "test-sb.pdf")

    for d in (data_a, data_b):
        response = await env.client.post(f"/api/v1/documents/{d['id']}/embed")
        assert response.status_code == 200

    async def query_embed(texts):
        vec = [0.0] * settings.EMBEDDING_DIMENSIONS
        vec[0] = 1.0
        return [vec for _ in texts]

    monkeypatch.setattr(embeddings, "embed_texts", query_embed)

    response = await env.client.post(
        "/api/v1/search",
        json={"query": "anything", "document_id": data_a["id"]},
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert results
    assert all(r["document_id"] == data_a["id"] for r in results)


async def test_semantic_search_validation(env):
    response = await env.client.post("/api/v1/search", json={"query": "   "})
    assert response.status_code == 422

    response = await env.client.post(
        "/api/v1/search", json={"query": "ok", "top_k": 0}
    )
    assert response.status_code == 422

    response = await env.client.post(
        "/api/v1/search", json={"query": "ok", "top_k": 100}
    )
    assert response.status_code == 422
