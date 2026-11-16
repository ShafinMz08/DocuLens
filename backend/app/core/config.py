
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
    )

    APP_NAME: str = "DocuLens"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    LOG_LEVEL: str = "info"

    DATABASE_URL: str
    TEST_DATABASE_URL: str | None = None
    SYNC_DATABASE_URL: str
    REDIS_URL: str = "redis://redis:6379/0"

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    DOCUMENT_STORAGE_DIR: str = "/app/storage/documents"
    MAX_UPLOAD_SIZE_BYTES: int = 20 * 1024 * 1024

    EMBEDDING_MODEL_NAME: str = "BAAI/bge-small-en-v1.5"
    EMBEDDING_MODEL_VERSION: str = "1"
    EMBEDDING_DIMENSIONS: int = 384
    EMBEDDING_BATCH_SIZE: int = 64
    EMBEDDING_STALE_SECONDS: int = 3600
    FASTEMBED_CACHE_DIR: str = "/app/storage/fastembed"

    # LLM providers
    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GROQ_API_KEY: str | None = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    LLM_PRIMARY_PROVIDER: str = "gemini"
    LLM_FALLBACK_PROVIDER: str | None = "groq"
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_OUTPUT_TOKENS: int = 1024
    LLM_TIMEOUT_SECONDS: float = 60.0

    # RAG / chat
    RAG_TOP_K: int = 6
    RAG_MIN_SIMILARITY: float = 0.2
    RAG_MAX_CONTEXT_CHARS: int = 12000
    CHAT_HISTORY_LIMIT: int = 10
    CHAT_MAX_QUESTION_LENGTH: int = 4000


settings = Settings()
