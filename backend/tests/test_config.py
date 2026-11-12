from app.core.config import settings


def test_required_settings_configured():
    assert settings.APP_NAME
    assert settings.APP_VERSION
    assert settings.DATABASE_URL.startswith("postgresql+asyncpg://")
    assert settings.SYNC_DATABASE_URL.startswith("postgresql://")
    assert settings.REDIS_URL.startswith("redis://")


def test_log_level_valid():
    import logging

    assert isinstance(getattr(logging, settings.LOG_LEVEL.upper(), None), int)
