import asyncio
import hashlib

import httpx

from app.adapters.tmdb import TmdbAdapter
from app.core.config import Settings


def make_settings(*, token: str = "test-token") -> Settings:
    return Settings(
        DATABASE_URL="postgresql+psycopg://cinesense:cinesense@localhost:5432/cinesense",
        TMDB_API_READ_ACCESS_TOKEN=token,
    )


class FakeResponse:
    def __init__(self, payload, *, status_code: int = 200, content: bytes | None = None):
        self._payload = payload
        self.status_code = status_code
        self.content = content if content is not None else b'{"results":[]}'
        self.request = httpx.Request("GET", "https://api.themoviedb.org/3/movie/550/recommendations")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad status", request=self.request, response=httpx.Response(self.status_code, request=self.request))

    def json(self):
        return self._payload


class FakeAsyncClient:
    payload = {"results": []}
    status_code = 200
    raised_exc = None
    seen_params = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, _url, *, params=None, headers=None):
        FakeAsyncClient.seen_params = params
        if FakeAsyncClient.raised_exc is not None:
            raise FakeAsyncClient.raised_exc
        return FakeResponse(FakeAsyncClient.payload, status_code=FakeAsyncClient.status_code, content=b'{"results":[1]}')


def reset_fake_client():
    FakeAsyncClient.payload = {"results": []}
    FakeAsyncClient.status_code = 200
    FakeAsyncClient.raised_exc = None
    FakeAsyncClient.seen_params = None


def test_get_seed_recommendations_returns_normalized_candidates(monkeypatch):
    reset_fake_client()
    FakeAsyncClient.payload = {
        "results": [
            {
                "id": 101,
                "title": "Heat 2",
                "original_language": "en",
                "release_date": "2027-12-01",
                "popularity": 44.5,
                "overview": "x",
                "poster_path": "/heat2.jpg",
            }
        ]
    }
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    adapter = TmdbAdapter(make_settings())
    candidates = asyncio.run(adapter.get_seed_recommendations("550", 5, region="US"))

    assert FakeAsyncClient.seen_params == {"page": "1", "region": "US"}
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source_movie_id == "101"
    assert candidate.title == "Heat 2"
    assert candidate.normalized_title == "heat 2"
    assert candidate.release_year == 2027
    assert candidate.media_type == "movie"
    assert candidate.original_language == "en"
    assert candidate.popularity == 44.5
    assert candidate.overview == "x"
    assert candidate.poster_path == "/heat2.jpg"
    assert candidate.source_url == "https://www.themoviedb.org/movie/101"
    assert candidate.fetch_status == "SUCCESS"
    assert candidate.parser_version == "tmdb-v1"
    assert candidate.raw_response_hash == hashlib.sha256(b'{"results":[1]}').hexdigest()
    assert candidate.fetched_at is not None


def test_get_seed_recommendations_caps_limit_at_20(monkeypatch):
    reset_fake_client()
    FakeAsyncClient.payload = {
        "results": [
            {"id": i, "title": f"Movie {i}", "release_date": "2026-01-01", "original_language": "en"}
            for i in range(1, 26)
        ]
    }
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    adapter = TmdbAdapter(make_settings())
    candidates = asyncio.run(adapter.get_seed_recommendations("550", 25))

    assert len(candidates) == 20
    assert candidates[0].source_movie_id == "1"
    assert candidates[-1].source_movie_id == "20"


def test_get_seed_recommendations_deduplicates_and_excludes_seed(monkeypatch):
    reset_fake_client()
    FakeAsyncClient.payload = {
        "results": [
            {"id": 550, "title": "Seed Movie", "release_date": "1999-01-01", "original_language": "en"},
            {"id": 77, "title": "Memento", "release_date": "2000-10-11", "original_language": "en"},
            {"id": 77, "title": "Memento", "release_date": "2000-10-11", "original_language": "en"},
            {"id": 603, "title": "The Matrix", "release_date": "1999-03-31", "original_language": "en"},
        ]
    }
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    adapter = TmdbAdapter(make_settings())
    candidates = asyncio.run(adapter.get_seed_recommendations("550", 10))

    assert [candidate.source_movie_id for candidate in candidates] == ["77", "603"]


def test_get_seed_recommendations_returns_empty_list_for_empty_results(monkeypatch):
    reset_fake_client()
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    adapter = TmdbAdapter(make_settings())
    candidates = asyncio.run(adapter.get_seed_recommendations("550", 10))

    assert candidates == []


def test_get_seed_recommendations_propagates_safe_provider_failure(monkeypatch):
    reset_fake_client()
    FakeAsyncClient.raised_exc = httpx.ConnectError("connection failed")
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    adapter = TmdbAdapter(make_settings(token="super-secret-token"))
    try:
        asyncio.run(adapter.get_seed_recommendations("550", 10))
    except httpx.ConnectError as exc:
        assert "super-secret-token" not in str(exc)
    else:
        raise AssertionError("expected ConnectError")

def test_get_seed_recommendations_propagates_safe_http_status_failure(monkeypatch):
    reset_fake_client()
    FakeAsyncClient.status_code = 503
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    adapter = TmdbAdapter(make_settings(token="super-secret-token"))
    try:
        asyncio.run(adapter.get_seed_recommendations("550", 10))
    except httpx.HTTPStatusError as exc:
        assert "super-secret-token" not in str(exc)
    else:
        raise AssertionError("expected HTTPStatusError")
