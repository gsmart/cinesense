import asyncio
import uuid

from datetime import UTC, datetime

import httpx
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.tmdb import TmdbCandidate
from app.db.base import Base
from app.models.movie import ExternalId, Movie
from app.services import LookupService


class SpyTmdb:
    def __init__(self, candidates=None, error=None):
        self.candidates = candidates or []
        self.error = error
        self.calls: list[tuple[str, int, str | None]] = []

    enabled = True

    async def get_seed_recommendations(self, source_movie_id: str, limit: int, region: str | None = None):
        self.calls.append((source_movie_id, limit, region))
        if self.error is not None:
            raise self.error
        return self.candidates


def make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return SessionLocal()


def make_seed_movie(*, media_type: str = "movie", with_tmdb_id: bool = True) -> Movie:
    movie = Movie(
        id=uuid.uuid4(),
        canonical_title="Seed Movie",
        normalized_title="seed movie",
        release_year=2008,
        media_type=media_type,
        original_language="en",
        overview="seed",
        runtime_minutes=None,
        poster_url=None,
    )
    movie.external_ids = []
    if with_tmdb_id:
        movie.external_ids.append(
            ExternalId(
                source="tmdb",
                source_movie_id="155",
                media_type="movie",
                source_url="https://www.themoviedb.org/movie/155",
            )
        )
    return movie


def make_candidate(source_movie_id: str, title: str, *, vote_average: float | None = None, vote_count: int | None = None, popularity: float | None = None) -> TmdbCandidate:
    return TmdbCandidate(
        source_movie_id=source_movie_id,
        title=title,
        normalized_title=title.lower(),
        release_year=2000,
        original_language="en",
        popularity=popularity,
        vote_average=vote_average,
        vote_count=vote_count,
        rating_scale="0-10" if vote_average is not None else None,
        source_url=f"https://www.themoviedb.org/movie/{source_movie_id}",
        fetched_at=datetime.now(UTC),
        fetch_status="SUCCESS",
        parser_version="tmdb-v1",
        raw_response_hash=f"hash-{source_movie_id}",
    )


def test_recommend_from_seed_movie_executes_adapter_persistence_and_ranking_in_order():
    session = make_session()
    seed = make_seed_movie()
    session.add(seed)
    session.commit()

    tmdb = SpyTmdb([make_candidate("201", "First"), make_candidate("202", "Second")])
    service = LookupService(session, tmdb)
    events: list[str] = []

    original_persist = service.persist_seed_recommendation_candidates
    original_rank = service.rank_seed_recommendation_candidates

    def wrapped_persist(*, seed_source_movie_id, candidates):
        events.append("persist")
        return original_persist(seed_source_movie_id=seed_source_movie_id, candidates=candidates)

    def wrapped_rank(movies):
        events.append("rank")
        return original_rank(movies)

    service.persist_seed_recommendation_candidates = wrapped_persist  # type: ignore[method-assign]
    service.rank_seed_recommendation_candidates = wrapped_rank  # type: ignore[method-assign]

    result = asyncio.run(service.recommend_from_seed_movie(seed_movie_id=str(seed.id), region="us", limit=2))

    assert result["status"] == "ok"
    assert tmdb.calls == [("155", 2, "US")]
    assert events == ["persist", "rank"]
    assert [item["tmdb_source_movie_id"] for item in result["results"]] == ["201", "202"]


def test_recommend_from_seed_movie_constrains_limit_to_one_and_twenty():
    session = make_session()
    seed = make_seed_movie()
    session.add(seed)
    session.commit()

    tmdb = SpyTmdb([make_candidate("201", "Only One")])
    service = LookupService(session, tmdb)

    low = asyncio.run(service.recommend_from_seed_movie(seed_movie_id=str(seed.id), limit=0))
    high = asyncio.run(service.recommend_from_seed_movie(seed_movie_id=str(seed.id), limit=99))

    assert low["limit"] == 1
    assert high["limit"] == 20
    assert tmdb.calls[0][1] == 1
    assert tmdb.calls[1][1] == 20


def test_recommend_from_seed_movie_returns_controlled_result_for_missing_seed():
    session = make_session()
    tmdb = SpyTmdb()
    service = LookupService(session, tmdb)

    result = asyncio.run(service.recommend_from_seed_movie(seed_movie_id=str(uuid.uuid4())))

    assert result["status"] == "seed_not_found"
    assert result["seed"] is None
    assert result["results"] == []
    assert tmdb.calls == []


def test_recommend_from_seed_movie_rejects_non_movie_seed():
    session = make_session()
    seed = make_seed_movie(media_type="series")
    session.add(seed)
    session.commit()

    tmdb = SpyTmdb()
    service = LookupService(session, tmdb)

    result = asyncio.run(service.recommend_from_seed_movie(seed_movie_id=str(seed.id)))

    assert result["status"] == "unsupported_media_type"
    assert result["seed"]["media_type"] == "series"
    assert tmdb.calls == []


def test_recommend_from_seed_movie_handles_missing_tmdb_external_id_without_provider_access():
    session = make_session()
    seed = make_seed_movie(with_tmdb_id=False)
    session.add(seed)
    session.commit()

    tmdb = SpyTmdb()
    service = LookupService(session, tmdb)

    result = asyncio.run(service.recommend_from_seed_movie(seed_movie_id=str(seed.id)))

    assert result["status"] == "missing_external_id"
    assert result["seed"]["movie_id"] == str(seed.id)
    assert tmdb.calls == []


def test_recommend_from_seed_movie_returns_empty_ranked_results_for_empty_provider_candidates():
    session = make_session()
    seed = make_seed_movie()
    session.add(seed)
    session.commit()

    tmdb = SpyTmdb([])
    service = LookupService(session, tmdb)

    result = asyncio.run(service.recommend_from_seed_movie(seed_movie_id=str(seed.id), limit=5))

    assert result["status"] == "ok"
    assert result["results"] == []


def test_recommend_from_seed_movie_propagates_safe_provider_failure_without_writes():
    session = make_session()
    seed = make_seed_movie()
    session.add(seed)
    session.commit()

    tmdb = SpyTmdb(error=httpx.ConnectError("boom"))
    service = LookupService(session, tmdb)

    try:
        asyncio.run(service.recommend_from_seed_movie(seed_movie_id=str(seed.id)))
    except RuntimeError as exc:
        assert str(exc) == "TMDB request failed"
    else:
        raise AssertionError("expected RuntimeError")

    movie_count = session.scalar(select(func.count()).select_from(Movie))
    external_count = session.scalar(select(func.count()).select_from(ExternalId).where(ExternalId.movie_id != seed.id))
    assert movie_count == 1
    assert external_count == 0


def test_recommend_from_seed_movie_repeated_calls_are_deterministic_without_duplicate_movies():
    session = make_session()
    seed = make_seed_movie()
    session.add(seed)
    session.commit()

    tmdb = SpyTmdb(
        [
            make_candidate("201", "First", vote_average=8.0, vote_count=1000, popularity=50.0),
            make_candidate("202", "Second", vote_average=7.0, vote_count=900, popularity=40.0),
        ]
    )
    service = LookupService(session, tmdb)

    first = asyncio.run(service.recommend_from_seed_movie(seed_movie_id=str(seed.id), limit=2))
    second = asyncio.run(service.recommend_from_seed_movie(seed_movie_id=str(seed.id), limit=2))

    assert first["results"] == second["results"]
    movie_count = session.scalar(select(func.count()).select_from(Movie))
    external_count = session.scalar(select(func.count()).select_from(ExternalId).where(ExternalId.movie_id != seed.id))
    assert movie_count == 3
    assert external_count == 2
