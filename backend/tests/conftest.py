from __future__ import annotations

import asyncio
import os

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.models import Base

_DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://id8:id8@localhost:5432/id8_test"
TEST_DATABASE_URL = os.environ.setdefault("TEST_DATABASE_URL", _DEFAULT_TEST_DATABASE_URL)
TEST_DATABASE_ADMIN_DB = os.environ.get("TEST_DATABASE_ADMIN_DB", "id8")

_ENUM_DDL = (
    """
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'design_provider_enum') THEN
        CREATE TYPE design_provider_enum AS ENUM ('stitch_mcp', 'internal_spec', 'manual_upload');
      END IF;
    END
    $$;
    """,
    """
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'model_profile_enum') THEN
        CREATE TYPE model_profile_enum AS ENUM ('primary', 'customtools', 'fallback');
      END IF;
    END
    $$;
    """,
    """
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'project_status_enum') THEN
        CREATE TYPE project_status_enum AS ENUM (
          'ideation',
          'prd_draft',
          'prd_approved',
          'design_draft',
          'design_approved',
          'tech_plan_draft',
          'tech_plan_approved',
          'codegen',
          'security_gate',
          'deploy_ready',
          'deploying',
          'deployed',
          'failed'
        );
      END IF;
    END
    $$;
    """,
    """
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'artifact_type_enum') THEN
        CREATE TYPE artifact_type_enum AS ENUM (
          'prd',
          'design_spec',
          'tech_plan',
          'code_snapshot',
          'security_report',
          'deploy_report'
        );
      END IF;
    END
    $$;
    """,
    """
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'approval_stage_enum') THEN
        CREATE TYPE approval_stage_enum AS ENUM ('prd', 'design', 'tech_plan', 'deploy');
      END IF;
    END
    $$;
    """,
)


def _ensure_test_database_exists(database_url: str) -> None:
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        return

    database_name = url.database
    if not database_name:
        raise RuntimeError("TEST_DATABASE_URL must include a database name")

    if database_name == TEST_DATABASE_ADMIN_DB:
        return

    admin_url = url.set(
        drivername="postgresql",
        database=TEST_DATABASE_ADMIN_DB,
    ).render_as_string(hide_password=False)
    quoted_database_name = database_name.replace('"', '""')

    async def _create_db_if_missing() -> None:
        conn = await asyncpg.connect(admin_url)
        try:
            exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", database_name)
            if exists is None:
                await conn.execute(f'CREATE DATABASE "{quoted_database_name}"')
        finally:
            await conn.close()

    asyncio.run(_create_db_if_missing())


def _initialize_schema(database_url: str) -> None:
    async def _create_all() -> None:
        bootstrap_engine = create_async_engine(database_url, echo=False, poolclass=NullPool)
        try:
            async with bootstrap_engine.begin() as conn:
                await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pgcrypto"'))
                for ddl in _ENUM_DDL:
                    await conn.execute(text(ddl))
                await conn.run_sync(Base.metadata.create_all)
        finally:
            await bootstrap_engine.dispose()

    asyncio.run(_create_all())


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_test_db() -> None:
    _ensure_test_database_exists(TEST_DATABASE_URL)
    _initialize_schema(TEST_DATABASE_URL)


engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)


@pytest_asyncio.fixture
async def db():
    """Provide an AsyncSession with a fresh connection per test, rolled back at the end."""
    conn = await engine.connect()
    txn = await conn.begin()
    session = AsyncSession(bind=conn, expire_on_commit=False)

    yield session

    await session.close()
    await txn.rollback()
    await conn.close()
