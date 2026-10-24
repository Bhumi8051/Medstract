"""Database engine and per-request sessions (SQLAlchemy 2, async, asyncpg)."""

import logging
from collections.abc import AsyncIterator

from fastapi import HTTPException, Request
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import Settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base class for all ORM tables (see app/db_models.py)."""


def create_engine(settings: Settings, **kwargs) -> AsyncEngine:
    # Creating the engine does not connect; the app starts even if PostgreSQL is down,
    # and only account features fail (with a 503) until it is back.
    return create_async_engine(settings.database_url.get_secret_value(), pool_pre_ping=True, **kwargs)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """One database session per request, from the sessionmaker created at startup.

    If PostgreSQL is down (OSError) or misconfigured (DBAPIError), the request
    gets a clear 503 instead of a stack trace. Only routes that use the database
    are affected; search and analysis keep working.
    """
    async with request.app.state.db_sessionmaker() as session:
        try:
            yield session
        except IntegrityError:
            raise  # constraint violations are handled by the routes
        except (OSError, DBAPIError) as exc:
            if isinstance(exc, ProgrammingError):  # e.g. missing table
                logger.error("Database schema problem (%s). Did you run: alembic upgrade head?", type(exc).__name__)
            else:
                logger.warning("Database unavailable: %s", type(exc).__name__)
            raise HTTPException(
                status_code=503,
                detail="Accounts are temporarily unavailable because of a database problem. "
                "Search and paper analysis still work.",
            ) from None
