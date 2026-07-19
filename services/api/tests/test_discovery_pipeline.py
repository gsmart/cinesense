import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.tmdb import TmdbCandidate
from app.db.base import Base
from app.models.movie import ExternalId, Movie, MovieAlias, Observation
from app.schemas.discovery import DiscoveryRequest
from app.services import LookupService


class SpyTmdb:
    def __init__(self, candidates=None):
        self.candidates = candidates or []
        self.calls: list[DiscoveryRequest] = []

    enabled = True

    async def discover_movies(self, request: DiscoveryRequest):
        self.calls.append(request)
        return self.candidates


def make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return SessionLocal()


def make_candidate(
    source_movie_id: str,
    title: str,
    *,
    year: int | None = None,
    language: str | None = "en",
    popularity: float | None = None,
    vote_average: float | None = None,
    vote_count: int | None = None,
    rating_scale: str | None = None,
    overview: str | None = None,
    poster_path: str | None = None,
    provider_position: int = 0,
    fetched_at: datetime | None = None,
    fetch_status: str = "SUCCESS",
    parser_version: str = "tmdb-v1",
    raw_response_hash: str | None = "raw-hash",
) -> TmdbCandidate:
    return TmdbCandidate(
        source_movie_id=source_movie_id,
        title=title,
        normalized_title=title.lower(),
        release_year=year,
        original_language=language,
        popularity=popularity,
        vote_average=vote_average,
        vote_count=vote_count,
        rating_scale=rating_scale,
        overview=overview,
        poster_path=poster_path,
        source_url=f"https://www.themoviedb.org/movie/{source_movie_id}",
        fetched_at=fetched_at or datetime.now(UTC),
        fetch_status=fetch_status,
        parser_version=parser_version,
        raw_response_hash=raw_response_hash,
        provider_position=provider_position,
    )


def make_existing_movie(source_movie_id: str, title: str = "Existing Movie") -> Movie:
    movie = Movie(
        id=uuid.uuid4(),
        canonical_title=title,
        normalized_title=title.lower(),
        release_year=2001,
        media_type="movie",
        original_language="en",
        overview="stored",
        runtime_minutes=None,
        poster_url=None,
    )
    movie.aliases = [MovieAlias(alias=title, normalized_alias=title.lower(), kind="title")]
    movie.external_ids = [
        ExternalId(
            source="tmdb",
            source_movie_id=source_movie_id,
            media_type="movie",
            source_url=f"https://www.themoviedb.org/movie/{source_movie_id}",
        )
    ]
    return movie


def test_discover_movies_executes_adapter_persistence_and_ranking_in_order():
    session = make_session()
    tmdb = SpyTmdb([make_candidate("201", "First"), make_candidate("202", "Second")])
    service = LookupService(session, tmdb)
    events: list[str] = []

    original_persist = service.persist_discovery_candidates
    original_rank = service.rank_discovery_candidates

    def wrapped_persist(*, candidates):
        events.append("persist")
        return original_persist(candidates=candidates)

    def wrapped_rank(movies):
        events.append("rank")
        return original_rank(movies)

    service.persist_discovery_candidates = wrapped_persist  # type: ignore[method-assign]
    service.rank_discovery_candidates = wrapped_rank  # type: ignore[method-assign]

    result = asyncio.run(service.discover_movies(request=DiscoveryRequest(genres=["action"], page_size=2)))

    assert result["status"] == "ok"
    assert tmdb.calls[0].genres == ["action"]
    assert events == ["persist", "rank"]
    assert [item["tmdb_source_movie_id"] for item in result["results"]] == ["201", "202"]


def test_persist_discovery_candidates_persists_new_candidates_and_reuses_existing_tmdb_movies():
    session = make_session()
    existing = make_existing_movie("101", "Stored Title")
    session.add(existing)
    session.commit()

    service = LookupService(session, SpyTmdb())
    fetched_at = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    persisted = service.persist_discovery_candidates(
        candidates=[
            make_candidate(
                "101",
                "Updated Title",
                year=2020,
                popularity=44.5,
                vote_average=8.3,
                vote_count=1200,
                rating_scale="0-10",
                fetched_at=fetched_at,
                raw_response_hash="candidate-hash",
            ),
            make_candidate("102", "Collateral", year=2004, overview="y"),
        ]
    )

    movie_count = session.scalar(select(func.count()).select_from(Movie))
    external_count = session.scalar(select(func.count()).select_from(ExternalId))
    observations = list(session.scalars(select(Observation).where(Observation.movie_id == existing.id)))
    by_signal = {observation.signal_type: observation for observation in observations}

    assert len(persisted) == 2
    assert persisted[0].id == existing.id
    assert persisted[0].canonical_title == "Updated Title"
    assert movie_count == 2
    assert external_count == 2
    assert float(by_signal["popularity"].numeric_value) == 44.5
    assert float(by_signal["audience_reception"].numeric_value) == 8.3
    assert by_signal["audience_reception"].evidence_count == 1200
    assert by_signal["audience_reception"].scale == "0-10"
    assert by_signal["popularity"].raw_response_hash == "candidate-hash"
    assert by_signal["popularity"].fetched_at == fetched_at.replace(tzinfo=None)


def test_persist_discovery_candidates_prevents_duplicates_and_is_idempotent():
    session = make_session()
    service = LookupService(session, SpyTmdb())

    first = service.persist_discovery_candidates(
        candidates=[
            make_candidate("101", "Heat 2", popularity=44.5, vote_average=8.3, vote_count=1200, rating_scale="0-10"),
            make_candidate("101", "Heat 2", popularity=44.5, vote_average=8.3, vote_count=1200, rating_scale="0-10"),
        ]
    )
    second = service.persist_discovery_candidates(
        candidates=[make_candidate("101", "Heat 2", popularity=55.0, vote_average=8.6, vote_count=1400, rating_scale="0-10")]
    )

    movie_count = session.scalar(select(func.count()).select_from(Movie))
    external_count = session.scalar(select(func.count()).select_from(ExternalId))
    observation_count = session.scalar(select(func.count()).select_from(Observation))

    assert first[0].id == second[0].id
    assert movie_count == 1
    assert external_count == 1
    assert observation_count == 2


def test_rank_discovery_candidates_keeps_missing_signals_explicit_and_uses_match_one_point_zero():
    session = make_session()
    service = LookupService(session, SpyTmdb())
    movie = make_existing_movie("101", "Bare")

    ranked = service.rank_discovery_candidates([movie])
    result = ranked[0]

    assert result["score_version"] == "cine-score-v1"
    assert result["score_components"]["query_match"] == 30.0
    assert "critic_consensus" in result["missing_signals"]
    assert "audience_reception" in result["missing_signals"]
    assert "popularity" in result["missing_signals"]
    assert result["freshness"]["critic_consensus"] == "MISSING"


def test_rank_discovery_candidates_higher_score_ranks_first_and_tie_breaks_deterministically():
    session = make_session()
    service = LookupService(session, SpyTmdb())

    low = make_existing_movie("200", "Low")
    high = make_existing_movie("100", "High")
    now = datetime(2026, 7, 19, tzinfo=UTC)
    high.observations = [
        Observation(
            source="tmdb",
            source_movie_id="100",
            signal_type="audience_reception",
            value={"vote_average": 9.0, "vote_count": 5000},
            scale="0-10",
            evidence_count=5000,
            numeric_value=9.0,
            fetched_at=now,
            fresh_until=now,
            stale_until=now,
            last_success_at=now,
            source_url="https://www.themoviedb.org/movie/100",
            fetch_status="SUCCESS",
            parser_version="tmdb-v1",
            raw_response_hash="aud",
        )
    ]
    ranked = service.rank_discovery_candidates([low, high])
    tied_movies = [make_existing_movie("200", "A"), make_existing_movie("100", "B")]
    tied_once = service.rank_discovery_candidates(tied_movies)
    tied_twice = service.rank_discovery_candidates(tied_movies)

    assert ranked[0]["tmdb_source_movie_id"] == "100"
    assert [item["tmdb_source_movie_id"] for item in tied_once] == ["200", "100"]
    assert tied_once == tied_twice


def test_discovery_pipeline_caps_results_at_twenty_and_returns_empty_when_candidates_are_empty():
    session = make_session()
    service = LookupService(session, SpyTmdb())

    persisted = service.persist_discovery_candidates(
        candidates=[make_candidate(str(index), f"Movie {index}") for index in range(1, 26)]
    )
    ranked = service.rank_discovery_candidates(persisted)
    empty = service.persist_discovery_candidates(candidates=[])

    assert len(persisted) == 20
    assert len(ranked) == 20
    assert empty == []
