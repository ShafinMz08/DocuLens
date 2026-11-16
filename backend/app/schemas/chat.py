import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.config import settings
from app.models import MessageRole


QuestionText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=settings.CHAT_MAX_QUESTION_LENGTH,
    ),
]


class ChatRequest(BaseModel):
    question: QuestionText
    conversation_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None


class Citation(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    chunk_index: int
    page_number: int | None
    excerpt: str | None = None
    score: float


class ChatResponse(BaseModel):
    answer: str
    conversation_id: uuid.UUID
    citations: list[Citation]
    provider: str | None = None
    model: str | None = None
    retrieved_chunks: int = 0


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: MessageRole
    content: str
    sources: list[dict[str, Any]] | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    created_at: datetime


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut] = []


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
