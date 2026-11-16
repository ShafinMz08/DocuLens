import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.models import (
    ChatMessage,
    Conversation,
    Document,
    DocumentChunk,
    DocumentStatus,
    MessageRole,
)
from app.services import embeddings, rag
from app.services.context_builder import RetrievedChunk
from app.services.document_processing import DocumentNotFoundError
from app.services.llm import LLMResponse
from app.services.rag import (
    NO_CONTEXT_ANSWER,
    ConversationNotFoundError,
    answer_question,
)


@pytest_asyncio.fixture
async def db_session():
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

    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


def _unit_vec(index: int) -> list[float]:
    vec = [0.0] * settings.EMBEDDING_DIMENSIONS
    vec[index] = 1.0
    return vec


async def _seed_document(
    session: AsyncSession,
    chunks: list[tuple[str, int | None, list[float]]],
    doc_name: str = "rag-doc.pdf",
) -> uuid.UUID:
    doc = Document(
        original_filename=doc_name,
        stored_filename=f"rag-{uuid.uuid4().hex}.pdf",
        content_type="application/pdf",
        file_size_bytes=100,
        storage_path="/tmp/x.pdf",
        status=DocumentStatus.COMPLETED,
    )
    session.add(doc)
    await session.flush()
    for i, (content, page, vec) in enumerate(chunks):
        session.add(
            DocumentChunk(
                document_id=doc.id,
                chunk_index=i,
                content=content,
                page_number=page,
                embedding=vec,
                embedding_model=embeddings.embedding_model_key(),
            )
        )
    await session.commit()
    return doc.id


async def _cleanup(session: AsyncSession, doc_ids: list, conv_ids: list) -> None:
    if conv_ids:
        await session.execute(
            delete(Conversation).where(Conversation.id.in_(conv_ids))
        )
    if doc_ids:
        await session.execute(delete(Document).where(Document.id.in_(doc_ids)))
    await session.commit()


class FakeLLMService:
    def __init__(self, text="The answer is grounded [1]."):
        self.text = text
        self.calls: list[list] = []

    async def generate(self, messages):
        self.calls.append(list(messages))
        return LLMResponse(
            text=self.text, provider="fake", model="fake-model"
        )


def _patch_query_embedding(monkeypatch, vec_index: int = 0):
    async def fake_embed(texts):
        return [_unit_vec(vec_index) for _ in texts]

    monkeypatch.setattr(embeddings, "embed_texts", fake_embed)


async def test_answer_question_grounded(db_session, monkeypatch):
    doc_id = await _seed_document(
        db_session,
        [("The capital of France is Paris.", 2, _unit_vec(0))],
    )
    _patch_query_embedding(monkeypatch)
    llm = FakeLLMService("Paris is the capital of France [1].")

    try:
        resp = await answer_question(
            "What is the capital of France?",
            conversation_id=None,
            document_id=None,
            db=db_session,
            llm_service=llm,
        )

        assert resp.answer == "Paris is the capital of France [1]."
        assert resp.provider == "fake"
        assert resp.model == "fake-model"
        assert resp.retrieved_chunks == 1
        assert len(resp.citations) == 1
        cit = resp.citations[0]
        assert cit.document_id == doc_id
        assert cit.document_name == "rag-doc.pdf"
        assert cit.page_number == 2
        assert cit.chunk_index == 0
        assert "Paris" in cit.excerpt

        # conversation + both messages persisted
        conv = await db_session.scalar(
            select(Conversation).where(Conversation.id == resp.conversation_id)
        )
        assert conv is not None
        msgs = (
            await db_session.execute(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conv.id)
                .order_by(ChatMessage.created_at, ChatMessage.id)
            )
        ).scalars().all()
        assert [m.role for m in msgs] == [MessageRole.USER, MessageRole.ASSISTANT]
        assert msgs[0].content == "What is the capital of France?"
        assert msgs[1].llm_provider == "fake"
        assert msgs[1].sources
    finally:
        await _cleanup(db_session, [doc_id], [resp.conversation_id])


async def test_answer_question_no_context(db_session, monkeypatch):
    _patch_query_embedding(monkeypatch)
    llm = FakeLLMService()

    resp = await answer_question(
        "Anything?",
        conversation_id=None,
        document_id=None,
        db=db_session,
        llm_service=llm,
    )

    assert resp.answer == NO_CONTEXT_ANSWER
    assert resp.citations == []
    assert resp.provider is None
    assert resp.retrieved_chunks == 0
    assert llm.calls == []  # LLM never invoked without evidence

    msgs = (
        await db_session.execute(
            select(ChatMessage).where(
                ChatMessage.conversation_id == resp.conversation_id
            )
        )
    ).scalars().all()
    assert len(msgs) == 2
    await _cleanup(db_session, [], [resp.conversation_id])


async def test_answer_question_below_threshold(db_session, monkeypatch):
    # chunk vector orthogonal to query -> cosine similarity 0 < threshold
    doc_id = await _seed_document(
        db_session, [("unrelated", None, _unit_vec(2))]
    )

    async def fake_embed(texts):
        return [_unit_vec(0) for _ in texts]

    monkeypatch.setattr(embeddings, "embed_texts", fake_embed)
    monkeypatch.setattr(settings, "RAG_MIN_SIMILARITY", 0.5)
    llm = FakeLLMService()

    resp = await answer_question(
        "question", None, None, db_session, llm_service=llm
    )
    assert resp.answer == NO_CONTEXT_ANSWER
    assert llm.calls == []
    await _cleanup(db_session, [doc_id], [resp.conversation_id])


async def test_answer_question_document_filter(db_session, monkeypatch):
    doc_a = await _seed_document(
        db_session, [("alpha content", 1, _unit_vec(0))], "a.pdf"
    )
    doc_b = await _seed_document(
        db_session, [("beta content", None, _unit_vec(0))], "b.pdf"
    )
    _patch_query_embedding(monkeypatch)
    llm = FakeLLMService("answer [1]")

    try:
        resp = await answer_question(
            "q", None, doc_a, db_session, llm_service=llm
        )
        assert resp.citations[0].document_id == doc_a
        assert resp.citations[0].document_name == "a.pdf"
        assert all(c.document_id != doc_b for c in resp.citations)
    finally:
        await _cleanup(db_session, [doc_a, doc_b], [resp.conversation_id])


async def test_answer_question_missing_document(db_session):
    with pytest.raises(DocumentNotFoundError):
        await answer_question(
            "q", None, uuid.uuid4(), db_session, llm_service=FakeLLMService()
        )


async def test_answer_question_missing_conversation(db_session):
    with pytest.raises(ConversationNotFoundError):
        await answer_question(
            "q",
            uuid.uuid4(),
            None,
            db_session,
            llm_service=FakeLLMService(),
        )


async def test_followup_uses_history(db_session, monkeypatch):
    doc_id = await _seed_document(
        db_session, [("some fact", 1, _unit_vec(0))]
    )
    _patch_query_embedding(monkeypatch)
    llm = FakeLLMService("first answer [1]")

    try:
        first = await answer_question(
            "first question?", None, None, db_session, llm_service=llm
        )

        llm.text = "follow-up answer [1]"
        second = await answer_question(
            "and what about it?",
            first.conversation_id,
            None,
            db_session,
            llm_service=llm,
        )
        assert second.conversation_id == first.conversation_id

        # the second LLM call must include prior conversation history
        second_call_messages = llm.calls[-1]
        roles = [m.role for m in second_call_messages]
        contents = [m.content for m in second_call_messages]
        assert "first question?" in contents
        assert "first answer [1]" in contents
        assert roles[0] == "system"
        assert roles[-1] == "user"
        # history must not include the pending question twice
        assert contents[-1].count("and what about it?") == 1
        assert "first question?" in contents[-1] or any(
            "first question?" in c for c in contents[:-1]
        )
    finally:
        await _cleanup(db_session, [doc_id], [first.conversation_id])


async def test_history_limit(db_session, monkeypatch):
    doc_id = await _seed_document(
        db_session, [("fact", 1, _unit_vec(0))]
    )
    _patch_query_embedding(monkeypatch)
    llm = FakeLLMService("ok [1]")

    conv_id = None
    try:
        for i in range(settings.CHAT_HISTORY_LIMIT + 2):
            resp = await answer_question(
                f"question {i}?",
                conv_id,
                None,
                db_session,
                llm_service=llm,
            )
            conv_id = resp.conversation_id

        last_call = llm.calls[-1]
        history_msgs = [
            m for m in last_call if m.role in ("user", "assistant")
        ]
        # system + context-question + bounded history
        assert len(history_msgs) <= settings.CHAT_HISTORY_LIMIT + 1
    finally:
        await _cleanup(db_session, [doc_id], [conv_id])


async def test_citations_fallback_to_context_chunks(
    db_session, monkeypatch
):
    doc_id = await _seed_document(
        db_session, [("chunk text here", 4, _unit_vec(0))]
    )
    _patch_query_embedding(monkeypatch)
    # answer without [n] markers -> all context chunks cited
    llm = FakeLLMService("answer with no markers")

    try:
        resp = await answer_question(
            "q", None, None, db_session, llm_service=llm
        )
        assert len(resp.citations) == 1
        assert resp.citations[0].document_id == doc_id
        assert resp.citations[0].page_number == 4
    finally:
        await _cleanup(db_session, [doc_id], [resp.conversation_id])


async def test_llm_failure_rolls_back_messages(db_session, monkeypatch):
    doc_id = await _seed_document(
        db_session, [("fact", 1, _unit_vec(0))]
    )
    _patch_query_embedding(monkeypatch)

    class FailingLLM:
        async def generate(self, messages):
            raise RuntimeError("provider exploded")

    with pytest.raises(RuntimeError):
        await answer_question(
            "q", None, None, db_session, llm_service=FailingLLM()
        )

    # no orphaned conversation/messages left behind
    convs = (
        await db_session.execute(select(Conversation))
    ).scalars().all()
    assert all(c.title != "q" for c in convs)
    await _cleanup(db_session, [doc_id], [])
