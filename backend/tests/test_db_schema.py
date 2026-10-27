"""
The app must be able to create its schema on an empty Postgres (as on
Azure Database for PostgreSQL), not only after scripts/init_db.sql.

Runs only when TEST_DATABASE_URL points at a disposable pgvector database
(CI provides one as a service container).
"""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.models import Base

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set")


async def test_init_db_creates_schema_on_empty_database(monkeypatch):
    from app import dependencies

    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP EXTENSION IF EXISTS vector CASCADE"))

    monkeypatch.setattr(dependencies, "engine", engine)
    await dependencies.init_db()
    await dependencies.init_db()  # second startup is a no-op

    async with engine.connect() as conn:
        tables = set((await conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ))).scalars())
        hnsw = (await conn.execute(text(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'idx_document_chunks_embedding'"
        ))).scalar_one()
    await engine.dispose()

    assert {"advisors", "clients", "documents", "document_chunks", "messages"} <= tables
    assert "USING hnsw (embedding vector_cosine_ops)" in hnsw
