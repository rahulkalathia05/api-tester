"""
Test fixtures for the API Tester backend.

Uses:
  - SQLite in-memory (via aiosqlite) — no PostgreSQL required
  - fakeredis — no Redis required
  - httpx.AsyncClient with ASGITransport — no live server required
"""
import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.dependencies import get_db, get_redis
from app.main import app

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine):
    TestSession = async_sessionmaker(test_engine, expire_on_commit=False)
    async with TestSession() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def fake_redis():
    client = FakeRedis()
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession, fake_redis: FakeRedis):
    async def _override_db():
        yield db_session

    def _override_redis():
        return fake_redis

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_redis] = _override_redis

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ── Auth helpers ───────────────────────────────────────────────────────────────

async def register_user(client: AsyncClient, email="test@example.com", password="Password1") -> dict:
    res = await client.post(
        "/auth/register",
        json={"name": "Test User", "email": email, "password": password},
    )
    assert res.status_code == 201, res.text
    return res.json()


async def auth_headers(client: AsyncClient, email="test@example.com", password="Password1") -> dict:
    data = await register_user(client, email, password)
    return {"Authorization": f"Bearer {data['access_token']}"}
