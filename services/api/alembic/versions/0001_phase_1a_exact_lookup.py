"""phase 1a exact lookup"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_phase_1a"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "movies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_title", sa.String(length=255), nullable=False),
        sa.Column("normalized_title", sa.String(length=255), nullable=False),
        sa.Column("release_year", sa.Integer(), nullable=True),
        sa.Column("media_type", sa.String(length=16), nullable=False),
        sa.Column("original_language", sa.String(length=16), nullable=True),
        sa.Column("overview", sa.Text(), nullable=True),
        sa.Column("runtime_minutes", sa.Integer(), nullable=True),
        sa.Column("poster_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_movies_normalized_title"), "movies", ["normalized_title"], unique=False)

    op.create_table(
        "movie_aliases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("movie_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.Column("normalized_alias", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("movie_id", "normalized_alias", name="uq_movie_alias"),
    )
    op.create_index(op.f("ix_movie_aliases_normalized_alias"), "movie_aliases", ["normalized_alias"], unique=False)

    op.create_table(
        "external_ids",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("movie_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_movie_id", sa.String(length=64), nullable=False),
        sa.Column("media_type", sa.String(length=16), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "source_movie_id", "media_type", name="uq_external_source_id"),
    )

    op.create_table(
        "observations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("movie_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_movie_id", sa.String(length=64), nullable=False),
        sa.Column("signal_type", sa.String(length=64), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("scale", sa.String(length=32), nullable=True),
        sa.Column("evidence_count", sa.Integer(), nullable=True),
        sa.Column("numeric_value", sa.Numeric(10, 4), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fresh_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stale_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("fetch_status", sa.String(length=32), nullable=False),
        sa.Column("parser_version", sa.String(length=32), nullable=False),
        sa.Column("raw_response_hash", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("movie_id", "source", "signal_type", name="uq_observation_signal"),
    )


def downgrade() -> None:
    op.drop_table("observations")
    op.drop_table("external_ids")
    op.drop_index(op.f("ix_movie_aliases_normalized_alias"), table_name="movie_aliases")
    op.drop_table("movie_aliases")
    op.drop_index(op.f("ix_movies_normalized_title"), table_name="movies")
    op.drop_table("movies")

