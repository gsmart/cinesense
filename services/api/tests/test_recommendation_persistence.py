import uuid

from datetime import UTC, datetime

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.tmdb import TmdbCandidate
from app.db.base import Base
from app.models.movie import ExternalId, Movie, MovieAlias, Observation
from app.services import LookupService


class DummyTmdb:
    enabled = True


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


def make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return SessionLocal()


def test_persist_seed_recommendation_candidates_persists_new_candidates():
    session = make_session()
    service = LookupService(session, DummyTmdb())

    persisted = service.persist_seed_recommendation_candidates(
        seed_source_movie_id="550",
        candidates=[
            make_candidate("101", "Heat 2", year=2027, overview="x", poster_path="/heat2.jpg"),
            make_candidate("102", "Collateral", year=2004, overview="y"),
        ],
    )

    movie_count = session.scalar(select(func.count()).select_from(Movie))
    external_count = session.scalar(select(func.count()).select_from(ExternalId))

    assert len(persisted) == 2
    assert movie_count == 2
    assert external_count == 2
    assert persisted[0].canonical_title == "Heat 2"
    assert persisted[0].poster_url == "https://image.tmdb.org/t/p/w500/heat2.jpg"


def test_persist_seed_recommendation_candidates_persists_valid_popularity():
    session = make_session()
    service = LookupService(session, DummyTmdb())

    persisted = service.persist_seed_recommendation_candidates(
        seed_source_movie_id="550",
        candidates=[make_candidate("101", "Heat 2", popularity=44.5)],
    )

    observation = session.scalar(select(Observation).where(Observation.movie_id == persisted[0].id, Observation.signal_type == "popularity"))

    assert observation is not None
    assert float(observation.numeric_value) == 44.5
    assert observation.value == {"popularity": 44.5}
    assert observation.scale is None


def test_persist_seed_recommendation_candidates_persists_valid_audience_reception_with_scale_and_evidence():
    session = make_session()
    service = LookupService(session, DummyTmdb())

    persisted = service.persist_seed_recommendation_candidates(
        seed_source_movie_id="550",
        candidates=[make_candidate("101", "Heat 2", vote_average=8.3, vote_count=1200, rating_scale="0-10")],
    )

    observation = session.scalar(
        select(Observation).where(Observation.movie_id == persisted[0].id, Observation.signal_type == "audience_reception")
    )

    assert observation is not None
    assert float(observation.numeric_value) == 8.3
    assert observation.evidence_count == 1200
    assert observation.scale == "0-10"
    assert observation.value == {"vote_average": 8.3, "vote_count": 1200}


def test_persist_seed_recommendation_candidates_stores_provenance_and_freshness_metadata():
    session = make_session()
    service = LookupService(session, DummyTmdb())
    fetched_at = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)

    persisted = service.persist_seed_recommendation_candidates(
        seed_source_movie_id="550",
        candidates=[
            make_candidate(
                "101",
                "Heat 2",
                popularity=44.5,
                fetched_at=fetched_at,
                fetch_status="SUCCESS",
                parser_version="tmdb-v1",
                raw_response_hash="candidate-hash",
            )
        ],
    )

    observation = session.scalar(select(Observation).where(Observation.movie_id == persisted[0].id, Observation.signal_type == "popularity"))

    assert observation is not None
    assert observation.source == "tmdb"
    assert observation.source_movie_id == "101"
    assert observation.source_url == "https://www.themoviedb.org/movie/101"
    assert observation.fetched_at == fetched_at.replace(tzinfo=None)
    assert observation.last_success_at == fetched_at.replace(tzinfo=None)
    assert observation.fetch_status == "SUCCESS"
    assert observation.parser_version == "tmdb-v1"
    assert observation.raw_response_hash == "candidate-hash"
    assert observation.fresh_until is not None
    assert observation.stale_until is not None
    assert observation.fresh_until > observation.fetched_at
    assert observation.stale_until > observation.fresh_until


def test_persist_seed_recommendation_candidates_reuses_existing_tmdb_movie():
    session = make_session()
    existing = make_existing_movie("101", "Stored Title")
    session.add(existing)
    session.commit()

    service = LookupService(session, DummyTmdb())
    persisted = service.persist_seed_recommendation_candidates(
        seed_source_movie_id="550",
        candidates=[make_candidate("101", "Updated Title", year=2020, overview="updated")],
    )

    movie_count = session.scalar(select(func.count()).select_from(Movie))
    external_count = session.scalar(select(func.count()).select_from(ExternalId))

    assert len(persisted) == 1
    assert persisted[0].id == existing.id
    assert persisted[0].canonical_title == "Updated Title"
    assert movie_count == 1
    assert external_count == 1


def test_persist_seed_recommendation_candidates_missing_signals_do_not_create_observations():
    session = make_session()
    service = LookupService(session, DummyTmdb())

    persisted = service.persist_seed_recommendation_candidates(
        seed_source_movie_id="550",
        candidates=[make_candidate("101", "Heat 2", popularity=None, vote_average=None, vote_count=None, rating_scale=None)],
    )

    observation_count = session.scalar(select(func.count()).select_from(Observation).where(Observation.movie_id == persisted[0].id))

    assert observation_count == 0


def test_persist_seed_recommendation_candidates_repeated_persistence_is_idempotent_for_observations():
    session = make_session()
    service = LookupService(session, DummyTmdb())

    first = make_candidate("101", "Heat 2", popularity=44.5, vote_average=8.3, vote_count=1200, rating_scale="0-10")
    second = make_candidate("101", "Heat 2", popularity=55.0, vote_average=8.6, vote_count=1400, rating_scale="0-10")

    first_result = service.persist_seed_recommendation_candidates(seed_source_movie_id="550", candidates=[first])
    second_result = service.persist_seed_recommendation_candidates(seed_source_movie_id="550", candidates=[second])

    observations = list(session.scalars(select(Observation).where(Observation.movie_id == first_result[0].id)))
    by_signal = {observation.signal_type: observation for observation in observations}

    assert first_result[0].id == second_result[0].id
    assert len(observations) == 2
    assert float(by_signal["popularity"].numeric_value) == 55.0
    assert float(by_signal["audience_reception"].numeric_value) == 8.6
    assert by_signal["audience_reception"].evidence_count == 1400


def test_persist_seed_recommendation_candidates_deduplicates_duplicate_candidates():
    session = make_session()
    service = LookupService(session, DummyTmdb())

    persisted = service.persist_seed_recommendation_candidates(
        seed_source_movie_id="550",
        candidates=[
            make_candidate("101", "Heat 2"),
            make_candidate("101", "Heat 2"),
            make_candidate("102", "Collateral"),
        ],
    )

    movie_count = session.scalar(select(func.count()).select_from(Movie))
    external_count = session.scalar(select(func.count()).select_from(ExternalId))

    assert [movie.canonical_title for movie in persisted] == ["Heat 2", "Collateral"]
    assert movie_count == 2
    assert external_count == 2


def test_persist_seed_recommendation_candidates_excludes_seed_movie():
    session = make_session()
    service = LookupService(session, DummyTmdb())

    persisted = service.persist_seed_recommendation_candidates(
        seed_source_movie_id="550",
        candidates=[
            make_candidate("550", "Seed Movie"),
            make_candidate("101", "Heat 2"),
        ],
    )

    movie_count = session.scalar(select(func.count()).select_from(Movie))

    assert [movie.canonical_title for movie in persisted] == ["Heat 2"]
    assert movie_count == 1


def test_persist_seed_recommendation_candidates_caps_processing_at_20_and_preserves_order():
    session = make_session()
    service = LookupService(session, DummyTmdb())

    persisted = service.persist_seed_recommendation_candidates(
        seed_source_movie_id="550",
        candidates=[make_candidate(str(index), f"Movie {index}") for index in range(1, 26)],
    )

    movie_count = session.scalar(select(func.count()).select_from(Movie))

    assert len(persisted) == 20
    assert [movie.canonical_title for movie in persisted[:3]] == ["Movie 1", "Movie 2", "Movie 3"]
    assert persisted[-1].canonical_title == "Movie 20"
    assert movie_count == 20


def test_persist_seed_recommendation_candidates_preserves_order_with_observations():
    session = make_session()
    service = LookupService(session, DummyTmdb())

    persisted = service.persist_seed_recommendation_candidates(
        seed_source_movie_id="550",
        candidates=[
            make_candidate("101", "Heat 2", popularity=44.5),
            make_candidate("102", "Collateral", vote_average=7.8, vote_count=900, rating_scale="0-10"),
            make_candidate("103", "Miami Vice", popularity=20.0),
        ],
    )

    assert [movie.canonical_title for movie in persisted] == ["Heat 2", "Collateral", "Miami Vice"]


def test_persist_seed_recommendation_candidates_returns_empty_without_writes():
    session = make_session()
    service = LookupService(session, DummyTmdb())

    persisted = service.persist_seed_recommendation_candidates(seed_source_movie_id="550", candidates=[])

    movie_count = session.scalar(select(func.count()).select_from(Movie))
    external_count = session.scalar(select(func.count()).select_from(ExternalId))

    assert persisted == []
    assert movie_count == 0
    assert external_count == 0
