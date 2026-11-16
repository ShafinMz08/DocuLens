import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import logger
from app.db.session import get_db
from app.models import ChatMessage, Conversation
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ConversationOut,
    ConversationSummary,
    MessageOut,
)
from app.services.document_processing import DocumentNotFoundError
from app.services.llm import LLMError
from app.services.rag import (
    ConversationNotFoundError,
    answer_question,
)

chat_router = APIRouter()
conversations_router = APIRouter()


@chat_router.post("", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await answer_question(
            question=request.question,
            conversation_id=request.conversation_id,
            document_id=request.document_id,
            db=db,
        )
    except DocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )
    except ConversationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    except LLMError as e:
        logger.error("Chat request failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The AI service is currently unavailable. Please try again later.",
        )
    except Exception:
        logger.exception("Chat request failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate an answer",
        )


@conversations_router.get("", response_model=list[ConversationSummary])
async def list_conversations(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    message_counts = (
        select(
            ChatMessage.conversation_id,
            func.count().label("message_count"),
        )
        .group_by(ChatMessage.conversation_id)
        .subquery()
    )
    result = await db.execute(
        select(Conversation, func.coalesce(message_counts.c.message_count, 0))
        .outerjoin(
            message_counts,
            message_counts.c.conversation_id == Conversation.id,
        )
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return [
        ConversationSummary(
            id=conv.id,
            title=conv.title,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            message_count=count,
        )
        for conv, count in result.all()
    ]


@conversations_router.get("/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    conversation = await db.scalar(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    messages = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.created_at, ChatMessage.id)
        )
    ).scalars().all()

    return ConversationOut(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[MessageOut.model_validate(m) for m in messages],
    )
