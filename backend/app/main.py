
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logger import logger
from app.core.redis import close_redis
from app.api.health import router as health_router
from app.api.documents import router as documents_router
from app.api.search import router as search_router
from app.api.chat import chat_router, conversations_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")

    try:
        yield
    finally:
        logger.info(f"Shutting down {settings.APP_NAME}")
        await close_redis()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(health_router, tags=["health"])
app.include_router(
    documents_router,
    prefix="/api/v1/documents",
    tags=["documents"],
)
app.include_router(
    search_router,
    prefix="/api/v1/search",
    tags=["search"],
)
app.include_router(
    chat_router,
    prefix="/api/v1/chat",
    tags=["chat"],
)
app.include_router(
    conversations_router,
    prefix="/api/v1/conversations",
    tags=["conversations"],
)
