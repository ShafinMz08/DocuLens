from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    APP_NAME: str = "DocuLens"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    LOG_LEVEL: str = "info"

    DATABASE_URL: str
    SYNC_DATABASE_URL: str
    REDIS_URL: str = "redis://redis:6379/0"

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
