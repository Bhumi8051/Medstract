"""Database tables. Schema changes go through Alembic migrations (backend/migrations)."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Uuid, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Load server-generated values (created_at, updated_at) back in the INSERT/UPDATE
# itself, so async code never triggers a hidden lazy load.
EAGER = {"eager_defaults": True}


class User(Base):
    __tablename__ = "users"
    __mapper_args__ = EAGER

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Stored lowercased by the app; the unique index on lower(email) enforces it in the database too.
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    # Argon2id hash (includes its own salt and parameters). Never the plain password.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    preferences: Mapped["ResearchPreferences"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False, lazy="raise"
    )

    __table_args__ = (Index("uq_users_email_lower", func.lower(email), unique=True),)


class UserSession(Base):
    """A login session. Only a SHA-256 hash of the cookie token is stored."""

    __tablename__ = "user_sessions"
    __mapper_args__ = EAGER

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class ResearchPreferences(Base):
    __tablename__ = "research_preferences"
    __mapper_args__ = EAGER

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    summary_level: Mapped[str] = mapped_column(String(20), nullable=False, server_default="college")
    research_interests: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)), nullable=False, server_default=text("'{}'::varchar[]")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="preferences", lazy="raise")

    __table_args__ = (
        CheckConstraint(
            "summary_level IN ('high_school', 'college', 'phd')", name="ck_research_preferences_summary_level"
        ),
    )


class SavedSearch(Base):
    __tablename__ = "saved_searches"
    __mapper_args__ = EAGER

    # Random UUIDs, so IDs can't be guessed or enumerated.
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    query: Mapped[str] = mapped_column(String(500), nullable=False)
    # Validated SavedSearchFilters (app/models.py) as JSON.
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_saved_searches_user_created", "user_id", text("created_at DESC")),)
