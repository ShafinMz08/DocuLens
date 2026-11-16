import uuid
from types import SimpleNamespace

import httpx
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models import (
    ChatMessage,
    Conversation,
    Document,
    DocumentChunk,
    DocumentStatus,
)
from app.services import embeddings, rag
from app.services.llm import LLMResponse


def _unit_vec(index: int) -> list[float]:
    vec = [0.0] * settings.EMBEDDING_DIMENSIONS
    vec[index] = 1.0
    return vec


class FakeLLMService:
    def __init__(self, text="API answer [1]."):
        self.text = text
        self.calls = []

    async def generate(self, messages):
        self.calls.append(list(messages))
        return LLMResponse(text=self.text, provider="fake", model="fake-model")


@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch):
    test_database_url = settings.TEST_DATABASE_URL

    if not test_database_url:
        raise RuntimeError("TEST_DATABASE_URL is required. Refusing to run tests.")

    test_database_name = make_url(test_database_url).database

    if test_database_name != "doculens_test":
        raise RuntimeError(
            f"Unsafe test database: {test_database_name}. Expected doculens_test."
        )

    engine = create_async_engine(test_database_url)
    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_db():
        async with factory() as session:
            yield session

    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db

    # deterministic embeddings + fake LLM for every test in this module
    async def fake_embed(texts):
        return [_unit_vec(0) for _ in texts]

    monkeypatch.setattr(embeddings, "embed_texts", fake_embed)
    llm = FakeLLMService()

    async def fake_get_llm_service():
        return llm

    monkeypatch.setattr(rag, "get_llm_service", fake_get_llm_service)

    test_env = SimpleNamespace(
        client=None,
        factory=factory,
        llm=llm,
        doc_ids=[],
        conv_ids=[],
    )

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            test_env.client = client
            yield test_env
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        try:
            async with factory() as session:
                if test_env.conv_ids:
                    await session.execute(
                        delete(Conversation).where(
                            Conversation.id.in_(test_env.conv_ids)
                        )
                    )
                if test_env.doc_ids:
                    await session.execute(
                        delete(Document).where(Document.id.in_(test_env.doc_ids))
                    )
                await session.commit()
        finally:
            await engine.dispose()


async def _seed_chunked_document(env) -> uuid.UUID:
    async with env.factory() as session:
        doc = Document(
            original_filename="chat-doc.pdf",
            stored_filename=f"chat-{uuid.uuid4().hex}.pdf",
            content_type="application/pdf",
            file_size_bytes=100,
            storage_path="/tmp/x.pdf",
            status=DocumentStatus.COMPLETED,
        )
        session.add(doc)
        await session.flush()
        session.add(
            DocumentChunk(
                document_id=doc.id,
                chunk_index=0,
                content="The project deadline is Friday.",
                page_number=1,
                embedding=_unit_vec(0),
                embedding_model=embeddings.embedding_model_key(),
            )
        )
        await session.commit()
        env.doc_ids.append(doc.id)
        return doc.id


async def test_chat_new_conversation(env):
    doc_id = await _seed_chunked_document(env)

    response = await env.client.post(
        "/api/v1/chat",
        json={"question": "When is the deadline?", "document_id": str(doc_id)},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["answer"] == "API answer [1]."
    assert data["provider"] == "fake"
    assert data["model"] == "fake-model"
    assert data["retrieved_chunks"] == 1
    assert len(data["citations"]) == 1
    assert data["citations"][0]["document_id"] == str(doc_id)
    assert data["citations"][0]["document_name"] == "chat-doc.pdf"
    assert data["citations"][0]["page_number"] == 1

    conv_id = uuid.UUID(data["conversation_id"])
    env.conv_ids.append(conv_id)

    # conversation retrievable with ordered messages
    response = await env.client.get(f"/api/v1/conversations/{conv_id}")
    assert response.status_code == 200
    conv = response.json()
    assert conv["id"] == str(conv_id)
    assert conv["title"] == "When is the deadline?"
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]
    assert conv["messages"][0]["content"] == "When is the deadline?"
    assert conv["messages"][1]["llm_provider"] == "fake"


async def test_chat_existing_conversation(env):
    doc_id = await _seed_chunked_document(env)

    r1 = await env.client.post("/api/v1/chat", json={"question": "first?"})
    assert r1.status_code == 200
    conv_id = r1.json()["conversation_id"]
    env.conv_ids.append(uuid.UUID(conv_id))

    env.llm.text = "second answer [1]"
    r2 = await env.client.post(
        "/api/v1/chat",
        json={"question": "follow up?", "conversation_id": conv_id},
    )
    assert r2.status_code == 200
    assert r2.json()["conversation_id"] == conv_id
    assert r2.json()["answer"] == "second answer [1]"

    # history included in second LLM call
    second_call = env.llm.calls[-1]
    assert any(m.content == "first?" for m in second_call)
    assert any(m.content == "API answer [1]." for m in second_call)

    response = await env.client.get(f"/api/v1/conversations/{conv_id}")
    roles = [m["role"] for m in response.json()["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"]


async def test_chat_empty_question_422(env):
    response = await env.client.post("/api/v1/chat", json={"question": "   "})
    assert response.status_code == 422

    response = await env.client.post(
        "/api/v1/chat", json={"question": "x" * 4001}
    )
    assert response.status_code == 422


async def test_chat_missing_document_404(env):
    response = await env.client.post(
        "/api/v1/chat",
        json={"question": "hi", "document_id": str(uuid.uuid4())},
    )
    assert response.status_code == 404


async def test_chat_missing_conversation_404(env):
    response = await env.client.post(
        "/api/v1/chat",
        json={"question": "hi", "conversation_id": str(uuid.uuid4())},
    )
    assert response.status_code == 404


async def test_chat_no_context_answer(env):
    # no documents seeded -> honest no-context response, no LLM call
    response = await env.client.post("/api/v1/chat", json={"question": "anything?"})
    assert response.status_code == 200
    data = response.json()
    assert data["citations"] == []
    assert data["provider"] is None
    assert "couldn't find" in data["answer"]
    assert env.llm.calls == []
    env.conv_ids.append(uuid.UUID(data["conversation_id"]))


async def test_chat_llm_failure_502(env, monkeypatch):
    doc_id = await _seed_chunked_document(env)

    class FailingLLM:
        async def generate(self, messages):
            raise RuntimeError("secret internal detail")

    async def failing_service():
        return FailingLLM()

    monkeypatch.setattr(rag, "get_llm_service", failing_service)

    response = await env.client.post("/api/v1/chat", json={"question": "q?"})
    assert response.status_code == 500
    assert "secret internal detail" not in response.text


async def test_get_missing_conversation_404(env):
    response = await env.client.get(f"/api/v1/conversations/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_list_conversations(env):
    r = await env.client.post("/api/v1/chat", json={"question": "list me"})
    assert r.status_code == 200
    env.conv_ids.append(uuid.UUID(r.json()["conversation_id"]))

    response = await env.client.get("/api/v1/conversations")
    assert response.status_code == 200
    items = response.json()
    ours = [c for c in items if c["id"] == str(env.conv_ids[0])]
    assert len(ours) == 1
    assert ours[0]["message_count"] == 2
    assert ours[0]["title"] == "list me"
