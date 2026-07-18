import uuid

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.tmdb import TmdbCandidate
from app.db.base import Base
from app.models.movie import ExternalId, Movie, MovieAlias
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
    overview: str | None = None,
    poster_path: str | None = None,
) -> TmdbCandidate:
    return TmdbCandidate(
        source_movie_id=source_movie_id,
        title=title,
        normalized_title=title.lower(),
        release_year=year,
        original_language=language,
        popularity=popularity,
        overview=overview,
        poster_path=poster_path,
        source_url=f"https://www.themoviedb.org/movie/{source_movie_id}",
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


def test_persist_seed_recommendation_candidates_returns_empty_without_writes():
    session = make_session()
    service = LookupService(session, DummyTmdb())

    persisted = service.persist_seed_recommendation_candidates(seed_source_movie_id="550", candidates=[])

    movie_count = session.scalar(select(func.count()).select_from(Movie))
    external_count = session.scalar(select(func.count()).select_from(ExternalId))

    assert persisted == []
    assert movie_count == 0
    assert external_count == 0
