"""Alembic migrations: they apply cleanly, roll back cleanly, and match the ORM models."""

import asyncio

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

import app.db_models  # noqa: F401
from app.db import Base
from tests.conftest import alembic_config, run_db


def test_downgrade_and_upgrade_round_trip(migrated_test_db):
    config = alembic_config(migrated_test_db)
    command.downgrade(config, "base")
    tables = {row[0] for row in run_db("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
    assert tables <= {"alembic_version"}

    command.upgrade(config, "head")
    tables = {row[0] for row in run_db("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
    assert {"users", "user_sessions", "research_preferences", "saved_searches"} <= tables


def test_models_and_migrations_are_in_sync(migrated_test_db):
    """Fails if someone changes app/db_models.py without adding a migration."""

    async def diff():
        engine = create_async_engine(migrated_test_db, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                return await conn.run_sync(
                    lambda sync_conn: compare_metadata(
                        MigrationContext.configure(sync_conn, opts={"compare_type": True}), Base.metadata
                    )
                )
        finally:
            await engine.dispose()

    assert asyncio.run(diff()) == []
