import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Movie(Base):
    __tablename__ = "movies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_title: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    release_year: Mapped[int | None] = mapped_column(Integer)
    media_type: Mapped[str] = mapped_column(String(16), nullable=False, default="movie")
    original_language: Mapped[str | None] = mapped_column(String(16))
    overview: Mapped[str | None] = mapped_column(Text)
    runtime_minutes: Mapped[int | None] = mapped_column(Integer)
    poster_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    aliases: Mapped[list["MovieAlias"]] = relationship(back_populates="movie", cascade="all, delete-orphan")
    external_ids: Mapped[list["ExternalId"]] = relationship(back_populates="movie", cascade="all, delete-orphan")
    observations: Mapped[list["Observation"]] = relationship(back_populates="movie", cascade="all, delete-orphan")


class MovieAlias(Base):
    __tablename__ = "movie_aliases"
    __table_args__ = (UniqueConstraint("movie_id", "normalized_alias", name="uq_movie_alias"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    movie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("movies.id", ondelete="CASCADE"), nullable=False)
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="alias")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    movie: Mapped[Movie] = relationship(back_populates="aliases")


class ExternalId(Base):
    __tablename__ = "external_ids"
    __table_args__ = (
        UniqueConstraint("source", "source_movie_id", "media_type", name="uq_external_source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    movie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("movies.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_movie_id: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    movie: Mapped[Movie] = relationship(back_populates="external_ids")


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (
        UniqueConstraint("movie_id", "source", "signal_type", name="uq_observation_signal"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    movie_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("movies.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_movie_id: Mapped[str] = mapped_column(String(64), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    scale: Mapped[str | None] = mapped_column(String(32))
    evidence_count: Mapped[int | None] = mapped_column(Integer)
    numeric_value: Mapped[float | None] = mapped_column(Numeric(10, 4))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fresh_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stale_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_url: Mapped[str | None] = mapped_column(Text)
    fetch_status: Mapped[str] = mapped_column(String(32), nullable=False, default="SUCCESS")
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False, default="tmdb-v1")
    raw_response_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    movie: Mapped[Movie] = relationship(back_populates="observations")

