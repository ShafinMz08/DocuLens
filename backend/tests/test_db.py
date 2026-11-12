from sqlalchemy import text

from app.db.session import engine


async def test_database_connection():
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar() == 1
