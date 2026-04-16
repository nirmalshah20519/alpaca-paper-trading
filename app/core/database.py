"""Database engine and session management."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.state.models import Base


def build_engine(database_url: str) -> AsyncEngine:
    """Create an async SQLAlchemy engine."""
    if database_url.startswith("sqlite+aiosqlite:///:memory:"):
        return create_async_engine(
            database_url,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return create_async_engine(database_url, pool_pre_ping=True)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create the session factory used by repositories."""
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_schema(engine: AsyncEngine) -> None:
    """Create the initial database schema for the MVP."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def ping_database(session_factory: async_sessionmaker[AsyncSession]) -> bool:
    """Run a cheap database liveness check."""
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
