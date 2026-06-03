from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from config.settings import get_settings
from database.models import Base

settings = get_settings()
engine: AsyncEngine = create_async_engine(settings.database_url, future=True, echo=False)
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_track_columns)


async def close_db() -> None:
    await engine.dispose()


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


def _ensure_track_columns(sync_conn) -> None:
    inspector = inspect(sync_conn)
    columns = {column["name"] for column in inspector.get_columns("tracks")}
    if "storage_bucket" not in columns:
        sync_conn.execute(text("ALTER TABLE tracks ADD COLUMN storage_bucket VARCHAR(255)"))
    if "storage_key" not in columns:
        sync_conn.execute(text("ALTER TABLE tracks ADD COLUMN storage_key VARCHAR(1024)"))
