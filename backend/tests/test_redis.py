from app.core.redis import ping_redis, close_redis


async def test_redis_connection():
    try:
        assert await ping_redis() is True
    finally:
        await close_redis()
