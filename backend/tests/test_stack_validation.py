"""Tests for stack JSON validation and defaults."""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.db import get_db
from app.main import create_app
from app.models.user import User
from app.schemas.stack import DEFAULT_STACK, StackJson

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://id8:id8@localhost:5432/id8_test",
)

_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
_SCAFFOLD_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest_asyncio.fixture
async def db():
    conn = await _engine.connect()
    txn = await conn.begin()
    session = AsyncSession(bind=conn, expire_on_commit=False)
    yield session
    await session.close()
    await txn.rollback()
    await conn.close()


@pytest_asyncio.fixture
async def client(db: AsyncSession):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def seed_user(db: AsyncSession) -> User:
    scaffold_owner_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
    scaffold_owner = await db.get(User, scaffold_owner_id)
    if scaffold_owner is None:
        scaffold_owner = User(id=scaffold_owner_id, email="operator+scaffold@id8.local", role="operator")
        db.add(scaffold_owner)
    user = await db.get(User, _SCAFFOLD_USER_ID)
    if user is None:
        user = User(id=_SCAFFOLD_USER_ID, email="test-stack@id8.local", role="operator")
        db.add(user)
    await db.flush()
    return user


class TestStackJsonValidation:
    def test_default_stack_is_valid(self) -> None:
        stack = DEFAULT_STACK
        assert stack.frontend_framework == "nextjs"
        assert stack.backend_framework == "nextjs"
        assert stack.database == "none"
        assert stack.database_provider == "none"
        assert stack.hosting_frontend == "vercel"
        assert stack.hosting_backend == "vercel"

    def test_valid_fixed_stack(self) -> None:
        stack = StackJson(
            frontend_framework="nextjs",
            backend_framework="nextjs",
            database="none",
            database_provider="none",
            hosting_frontend="vercel",
            hosting_backend="vercel",
        )
        assert stack.frontend_framework == "nextjs"
        assert stack.hosting_backend == "vercel"

    def test_invalid_hosting_frontend(self) -> None:
        with pytest.raises(ValidationError):
            StackJson(
                frontend_framework="nextjs",
                backend_framework="nextjs",
                database="none",
                database_provider="none",
                hosting_frontend="netlify",  # type: ignore[arg-type]
                hosting_backend="vercel",
            )

    def test_invalid_hosting_backend(self) -> None:
        with pytest.raises(ValidationError):
            StackJson(
                frontend_framework="nextjs",
                backend_framework="nextjs",
                database="none",
                database_provider="none",
                hosting_frontend="vercel",
                hosting_backend="aws",  # type: ignore[arg-type]
            )

    def test_invalid_framework(self) -> None:
        with pytest.raises(ValidationError):
            StackJson(
                frontend_framework="angular",  # type: ignore[arg-type]
                backend_framework="nextjs",
                database="none",
                database_provider="none",
                hosting_frontend="vercel",
                hosting_backend="vercel",
            )

    def test_reject_non_none_database_provider(self) -> None:
        with pytest.raises(ValidationError):
            StackJson(
                frontend_framework="nextjs",
                backend_framework="nextjs",
                database="none",
                database_provider="local",  # type: ignore[arg-type]
                hosting_frontend="vercel",
                hosting_backend="vercel",
            )

    def test_reject_non_none_database(self) -> None:
        with pytest.raises(ValidationError):
            StackJson(
                frontend_framework="nextjs",
                backend_framework="nextjs",
                database="postgresql",  # type: ignore[arg-type]
                database_provider="none",
                hosting_frontend="vercel",
                hosting_backend="vercel",
            )


class TestCreateProjectWithStack:
    @pytest.mark.asyncio
    async def test_create_with_default_stack(
        self, client: AsyncClient, seed_user: User
    ) -> None:
        resp = await client.post(
            "/v1/projects", json={"title": "CRM", "initial_prompt": "Build me a CRM"}
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["stack_json"] is not None
        assert data["stack_json"]["frontend_framework"] == "nextjs"
        assert data["stack_json"]["hosting_frontend"] == "vercel"

    @pytest.mark.asyncio
    async def test_reject_non_hostable_stack(
        self, client: AsyncClient, seed_user: User
    ) -> None:
        resp = await client.post(
            "/v1/projects",
            json={
                "title": "Invalid Stack",
                "initial_prompt": "Build me a thing",
                "stack_json": {
                    "frontend_framework": "nextjs",
                    "backend_framework": "nextjs",
                    "database": "none",
                    "database_provider": "none",
                    "hosting_frontend": "netlify",
                    "hosting_backend": "vercel",
                },
            },
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_reject_non_fixed_database(
        self, client: AsyncClient, seed_user: User
    ) -> None:
        resp = await client.post(
            "/v1/projects",
            json={
                "title": "Invalid Database",
                "initial_prompt": "Build me a thing",
                "stack_json": {
                    "frontend_framework": "nextjs",
                    "backend_framework": "nextjs",
                    "database": "mysql",
                    "database_provider": "none",
                    "hosting_frontend": "vercel",
                    "hosting_backend": "vercel",
                },
            },
        )
        assert resp.status_code == 422
