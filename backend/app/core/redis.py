import redis.asyncio as aioredis
from app.core.config import settings
from app.core.logger import logger

redis_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global redis_client
    if redis_client is None:
        redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return redis_client


async def ping_redis() -> bool:
    client = await get_redis()
    return bool(await client.ping())


async def close_redis() -> None:
    global redis_client
    if redis_client is not None:
        await redis_client.aclose()
        redis_client = None
        logger.info("Redis connection closed")
