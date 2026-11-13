from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import logger
from app.db.session import get_db
from app.schemas.search import SearchRequest, SearchResponse
from app.services import embeddings

router = APIRouter()


@router.post("", response_model=SearchResponse)
async def semantic_search_endpoint(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await embeddings.semantic_search(
            query=request.query,
            top_k=request.top_k,
            document_id=request.document_id,
            db=db,
        )
    except Exception:
        logger.exception("Semantic search failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Search failed",
        )
