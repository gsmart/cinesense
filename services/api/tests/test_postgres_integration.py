import asyncio
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.adapters.tmdb import TmdbCandidate, TmdbMovieBundle
from app.db.base import Base
from app.models.movie import ExternalId, Movie, Observation
from app.services import LookupService


pytestmark = pytest.mark.integration


TEST_DATABASE_URL = os.environ.get(
    "CINESENSE_TEST_DATABASE_URL",
    "postgresql+psycopg://cinesense:cinesense@localhost:5432/postgres",
)


def _admin_connection_dsn() -> str:
    return TEST_DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")


def _random_db_name() -> str:
    return f"cinesense_test_{uuid.uuid4().hex[:10]}"


def _safe_db_error(exc: psycopg.Error) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return message.replace(_admin_connection_dsn(), "<redacted-dsn>")


@pytest.fixture()
def postgres_session_factory():
    admin_dsn = _admin_connection_dsn()
    db_name = _random_db_name()
    try:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{db_name}"')
    except psycopg.Error as exc:
        pytest.fail(f"postgres integration setup failed: {_safe_db_error(exc)}")

    db_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + f"/{db_name}"
    engine = create_engine(db_url, future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    try:
        yield SessionLocal
    finally:
        engine.dispose()
        try:
            with psycopg.connect(admin_dsn, autocommit=True) as conn:
                conn.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                    (db_name,),
                )
                conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        except psycopg.Error as exc:
            pytest.fail(f"postgres integration cleanup failed: {_safe_db_error(exc)}")


class FakeTmdbAdapter:
    enabled = True

    async def search_titles(self, query: str, year: int | None, media_type: str):
        return [
            TmdbCandidate(
                source_movie_id="999",
                title=query,
                normalized_title=query.lower(),
                release_year=year,
                original_language="en",
                popularity=42.0,
            )
        ]

    async def get_movie_bundle(self, source_movie_id: str, region: str | None):
        now = datetime.now(UTC)
        return TmdbMovieBundle(
            source_movie_id=source_movie_id,
            source_url=f"https://www.themoviedb.org/movie/{source_movie_id}",
            canonical_title="Heat",
            normalized_title="heat",
            release_year=1995,
            original_language="en",
            overview="x",
            runtime_minutes=170,
            poster_url=None,
            aliases=["Heat"],
            observations=[
                {
                    "signal_type": "title_metadata",
                    "value": {"title": "Heat", "release_date": "1995-12-15", "region": region},
                    "numeric_value": None,
                    "evidence_count": None,
                    "scale": None,
                    "fetched_at": now,
                    "fresh_until": now + timedelta(days=30),
                    "stale_until": now + timedelta(days=90),
                    "last_success_at": now,
                    "source_url": f"https://www.themoviedb.org/movie/{source_movie_id}",
                    "fetch_status": "SUCCESS",
                    "parser_version": "tmdb-v1",
                    "raw_response_hash": "meta",
                    "source_movie_id": source_movie_id,
                },
                {
                    "signal_type": "audience_reception",
                    "value": {"vote_average": 8.0, "vote_count": 1000},
                    "numeric_value": 8.0,
                    "evidence_count": 1000,
                    "scale": "0-10",
                    "fetched_at": now,
                    "fresh_until": now + timedelta(days=7),
                    "stale_until": now + timedelta(days=30),
                    "last_success_at": now,
                    "source_url": f"https://www.themoviedb.org/movie/{source_movie_id}",
                    "fetch_status": "SUCCESS",
                    "parser_version": "tmdb-v1",
                    "raw_response_hash": "aud",
                    "source_movie_id": source_movie_id,
                },
            ],
        )


def test_concurrent_identical_lookup_creates_one_movie_and_one_external_id(postgres_session_factory):
    adapter = FakeTmdbAdapter()

    def worker():
        session: Session = postgres_session_factory()
        try:
            service = LookupService(session, adapter)
            return asyncio.run(service.lookup(title="Heat", year=1995, region=None, media_type="movie"))
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _n: worker(), range(5)))

    movie_ids = {result["movie"]["movie_id"] for result in results}
    assert len(movie_ids) == 1

    session: Session = postgres_session_factory()
    try:
        movie_count = session.scalar(select(func.count()).select_from(Movie).where(Movie.normalized_title == "heat"))
        external_id_count = session.scalar(
            select(func.count()).select_from(ExternalId).where(
                ExternalId.source == "tmdb",
                ExternalId.source_movie_id == "999",
            )
        )
        observation_count = session.scalar(
            select(func.count()).select_from(Observation).join(Movie).where(Movie.normalized_title == "heat")
        )
        movie = session.scalar(
            select(Movie)
            .options(joinedload(Movie.external_ids), joinedload(Movie.observations))
            .where(Movie.normalized_title == "heat")
        )
    finally:
        session.close()

    assert movie_count == 1
    assert external_id_count == 1
    assert observation_count == 2
    assert movie is not None
