from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# SQLite (used in tests) does not support pool_size / max_overflow.
_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

_pool_kwargs = (
    {}
    if _is_sqlite
    else {"pool_size": 10, "max_overflow": 20, "pool_pre_ping": True}
)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    **_pool_kwargs,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


class Base(DeclarativeBase):
    """Shared declarative base — all ORM models inherit from this."""
    pass
