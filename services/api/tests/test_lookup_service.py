import uuid
from datetime import UTC, datetime, timedelta

from app.models.movie import ExternalId, Movie, MovieAlias, Observation
from app.services import LookupService


def make_movie(*, title: str = "The Dark Knight", year: int = 2008, fresh_state: str = "fresh") -> Movie:
    movie = Movie(
        id=uuid.uuid4(),
        canonical_title=title,
        normalized_title=title.lower(),
        release_year=year,
        media_type="movie",
        original_language="en",
        overview="x",
        runtime_minutes=100,
        poster_url=None,
    )
    now = datetime.now(UTC)
    if fresh_state == "fresh":
        fresh_until = now + timedelta(days=1)
        stale_until = now + timedelta(days=2)
    elif fresh_state == "stale":
        fresh_until = now - timedelta(hours=1)
        stale_until = now + timedelta(days=1)
    else:
        fresh_until = now - timedelta(days=2)
        stale_until = now - timedelta(hours=1)
    movie.aliases = [MovieAlias(alias=title, normalized_alias=title.lower(), kind="title")]
    movie.external_ids = [
        ExternalId(
            source="tmdb",
            source_movie_id="155",
            media_type="movie",
            source_url="https://www.themoviedb.org/movie/155",
            first_seen_at=now,
            last_seen_at=now,
        )
    ]
    movie.observations = [
        Observation(
            source="tmdb",
            source_movie_id="155",
            signal_type="title_metadata",
            value={"title": title, "release_date": f"{year}-07-18"},
            scale=None,
            evidence_count=None,
            numeric_value=None,
            fetched_at=now,
            fresh_until=fresh_until,
            stale_until=stale_until,
            last_success_at=now,
            source_url="https://www.themoviedb.org/movie/155",
            fetch_status="SUCCESS",
            parser_version="tmdb-v1",
            raw_response_hash="x",
        ),
        Observation(
            source="tmdb",
            source_movie_id="155",
            signal_type="audience_reception",
            value={"vote_average": 8.5, "vote_count": 30000},
            scale="0-10",
            evidence_count=30000,
            numeric_value=8.5,
            fetched_at=now,
            fresh_until=now + timedelta(days=1),
            stale_until=now + timedelta(days=2),
            last_success_at=now,
            source_url="https://www.themoviedb.org/movie/155",
            fetch_status="SUCCESS",
            parser_version="tmdb-v1",
            raw_response_hash="y",
        ),
    ]
    return movie


class FakeResult:
    def __init__(self, movies):
        self._movies = movies

    def unique(self):
        return self._movies


class FakeSession:
    def __init__(self, movies):
        self._movies = movies

    def scalars(self, _stmt):
        return FakeResult(self._movies)

    def scalar(self, _stmt):
        return None


class SpyTmdb:
    def __init__(self):
        self.search_calls = 0

    enabled = True

    async def search_titles(self, *_args, **_kwargs):
        self.search_calls += 1
        return []


def test_lookup_uses_fresh_local_data_without_tmdb_call():
    tmdb = SpyTmdb()
    service = LookupService(FakeSession([make_movie(fresh_state="fresh")]), tmdb)

    import asyncio

    result = asyncio.run(service.lookup(title="the dark knight", year=2008, region=None, media_type="movie"))
    assert result["source"] == "local_cache"
    assert result["movie"]["score"]["version"] == "cine-score-v1"
    assert result["movie"]["score"]["total"] == 80.25
    assert tmdb.search_calls == 0


def test_lookup_uses_stale_usable_local_data_without_tmdb_call():
    tmdb = SpyTmdb()
    service = LookupService(FakeSession([make_movie(fresh_state="stale")]), tmdb)

    import asyncio

    result = asyncio.run(service.lookup(title="the dark knight", year=2008, region=None, media_type="movie"))
    assert result["source"] == "local_cache"
    assert result["movie"]["freshness"]["title_metadata"] == "STALE_USABLE"
    assert tmdb.search_calls == 0
