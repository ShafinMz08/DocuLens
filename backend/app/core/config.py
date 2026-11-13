
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


settings = Settings()
