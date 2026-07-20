import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.routes.lookup import get_db
from app.services import LookupService


class DummyDb:
    pass


def _valid_request():
    return {
        "genres": [" drama ", "action"],
        "original_language": " EN ",
        "release_year_min": 1990,
        "page": 2,
        "page_size": 2,
    }


def test_discovery_api_valid_request_returns_200_and_normalized_request(monkeypatch):
    first_id = str(uuid.uuid4())

    async def fake_discover(self, *, request):
        assert request.genres == ["action", "drama"]
        assert request.original_language == "en"
        assert request.page == 2
        assert request.page_size == 2
        return {
            "status": "ok",
            "results": [
                {
                    "movie": {
                        "movie_id": first_id,
                        "canonical_title": "Heat",
                        "release_year": 1995,
                        "media_type": "movie",
                        "original_language": "en",
                        "overview": "x",
                        "poster_url": None,
                    },
                    "tmdb_source_movie_id": "949",
                    "provider_position": 0,
                    "score": 82.5,
                    "score_version": "cine-score-v1",
                    "score_components": {
                        "query_match": 30.0,
                        "audience_reception": 20.0,
                        "critic_consensus": None,
                        "popularity": 4.0,
                        "evidence_confidence": 16.5,
                        "data_coverage": 12.0,
                    },
                    "missing_signals": ["critic_consensus"],
                    "provenance": {
                        "source": "tmdb",
                        "source_movie_id": "949",
                        "source_url": "https://www.themoviedb.org/movie/949",
                    },
                    "freshness": {
                        "audience_reception": "FRESH",
                        "popularity": "FRESH",
                        "critic_consensus": "MISSING",
                    },
                }
            ],
            "page": {
                "page": 2,
                "requested_page_size": 2,
                "returned_count": 1,
                "max_page_size": 20,
            },
        }

    monkeypatch.setattr(LookupService, "discover_movies", fake_discover)
    app.dependency_overrides[get_db] = lambda: DummyDb()
    client = TestClient(app)

    response = client.post("/api/v1/discover", json=_valid_request())

    assert response.status_code == 200
    body = response.json()
    assert body["request"] == {
        "media_type": "movie",
        "genres": ["action", "drama"],
        "original_language": "en",
        "region": None,
        "release_year_min": 1990,
        "release_year_max": None,
        "runtime_minutes_min": None,
        "runtime_minutes_max": None,
        "minimum_evidence_count": 0,
        "availability_required": False,
        "page": 2,
        "page_size": 2,
        "include_shadow": False,
    }
    assert body["results"][0]["tmdb_source_movie_id"] == "949"
    assert body["page"] == {
        "page": 2,
        "requested_page_size": 2,
        "returned_count": 1,
        "max_page_size": 20,
    }
    app.dependency_overrides.clear()


def test_discovery_api_preserves_orchestration_order_and_serializes_scores_without_recalculation(monkeypatch):
    first_id = str(uuid.uuid4())
    second_id = str(uuid.uuid4())

    async def fake_discover(self, *, request):
        return {
            "status": "ok",
            "results": [
                {
                    "movie": {
                        "movie_id": first_id,
                        "canonical_title": "First",
                        "release_year": 1995,
                        "media_type": "movie",
                        "original_language": "en",
                        "overview": "one",
                        "poster_url": None,
                    },
                    "tmdb_source_movie_id": "101",
                    "provider_position": 0,
                    "score": 80.0,
                    "score_version": "cine-score-v1",
                    "score_components": {"query_match": 30.0, "audience_reception": 20.0, "critic_consensus": None, "popularity": 5.0, "evidence_confidence": 15.0, "data_coverage": 12.0},
                    "missing_signals": ["critic_consensus"],
                    "provenance": {"source": "tmdb", "source_movie_id": "101", "source_url": "https://www.themoviedb.org/movie/101"},
                    "freshness": {"audience_reception": "FRESH", "popularity": "FRESH", "critic_consensus": "MISSING"},
                    "raw_payload": {"should": "not leak"},
                },
                {
                    "movie": {
                        "movie_id": second_id,
                        "canonical_title": "Second",
                        "release_year": 1999,
                        "media_type": "movie",
                        "original_language": "en",
                        "overview": "two",
                        "poster_url": None,
                    },
                    "tmdb_source_movie_id": "202",
                    "provider_position": 1,
                    "score": 70.0,
                    "score_version": "cine-score-v1",
                    "score_components": {"query_match": 28.5, "audience_reception": 18.0, "critic_consensus": None, "popularity": 4.0, "evidence_confidence": 14.0, "data_coverage": 12.0},
                    "missing_signals": ["critic_consensus"],
                    "provenance": {"source": "tmdb", "source_movie_id": "202", "source_url": "https://www.themoviedb.org/movie/202"},
                    "freshness": {"audience_reception": "FRESH", "popularity": "FRESH", "critic_consensus": "MISSING"},
                },
            ],
            "page": {"page": 1, "requested_page_size": 20, "returned_count": 2, "max_page_size": 20},
        }

    monkeypatch.setattr(LookupService, "discover_movies", fake_discover)
    app.dependency_overrides[get_db] = lambda: DummyDb()
    client = TestClient(app)

    first = client.post("/api/v1/discover", json={"genres": ["action"]})
    second = client.post("/api/v1/discover", json={"genres": ["action"]})

    assert first.status_code == 200
    assert [item["tmdb_source_movie_id"] for item in first.json()["results"]] == ["101", "202"]
    assert first.json()["results"][0]["score"] == 80.0
    assert first.json()["results"][0]["score_components"]["query_match"] == 30.0
    assert "raw_payload" not in first.text
    assert first.json()["results"] == second.json()["results"]
    app.dependency_overrides.clear()


def test_discovery_api_never_returns_more_than_twenty_results(monkeypatch):
    async def fake_discover(self, *, request):
        return {
            "status": "ok",
            "results": [
                {
                    "movie": {
                        "movie_id": str(uuid.uuid4()),
                        "canonical_title": f"Movie {index}",
                        "release_year": 2000,
                        "media_type": "movie",
                        "original_language": "en",
                        "overview": None,
                        "poster_url": None,
                    },
                    "tmdb_source_movie_id": str(index),
                    "provider_position": index - 1,
                    "score": float(index),
                    "score_version": "cine-score-v1",
                    "score_components": {"query_match": 30.0, "audience_reception": None, "critic_consensus": None, "popularity": None, "evidence_confidence": None, "data_coverage": 3.0},
                    "missing_signals": ["critic_consensus", "audience_reception", "popularity"],
                    "provenance": {"source": "tmdb", "source_movie_id": str(index), "source_url": None},
                    "freshness": {"audience_reception": "MISSING", "popularity": "MISSING", "critic_consensus": "MISSING"},
                }
                for index in range(1, 26)
            ],
            "page": {"page": 1, "requested_page_size": 20, "returned_count": 25, "max_page_size": 20},
        }

    monkeypatch.setattr(LookupService, "discover_movies", fake_discover)
    app.dependency_overrides[get_db] = lambda: DummyDb()
    client = TestClient(app)
    response = client.post("/api/v1/discover", json={"genres": ["action"]})

    assert response.status_code == 200
    assert len(response.json()["results"]) == 20
    app.dependency_overrides.clear()


def test_discovery_api_empty_results_return_200(monkeypatch):
    async def fake_discover(self, *, request):
        return {
            "status": "ok",
            "results": [],
            "page": {"page": 1, "requested_page_size": 20, "returned_count": 0, "max_page_size": 20},
        }

    monkeypatch.setattr(LookupService, "discover_movies", fake_discover)
    app.dependency_overrides[get_db] = lambda: DummyDb()
    client = TestClient(app)
    response = client.post("/api/v1/discover", json={"genres": ["action"]})

    assert response.status_code == 200
    assert response.json()["results"] == []
    app.dependency_overrides.clear()


def test_discovery_api_unrestricted_request_returns_422():
    client = TestClient(app)
    response = client.post("/api/v1/discover", json={})
    assert response.status_code == 422


def test_discovery_api_malformed_request_returns_422():
    client = TestClient(app)
    response = client.post("/api/v1/discover", json={"genres": ["action"], "page_size": 21})
    assert response.status_code == 422


def test_discovery_api_unsupported_availability_returns_controlled_422(monkeypatch):
    async def fake_discover(self, *, request):
        return {
            "status": "unsupported_filter",
            "unsupported_filter": "availability_required",
            "results": [],
            "page": {"page": 1, "requested_page_size": 20, "returned_count": 0, "max_page_size": 20},
        }

    monkeypatch.setattr(LookupService, "discover_movies", fake_discover)
    app.dependency_overrides[get_db] = lambda: DummyDb()
    client = TestClient(app)
    response = client.post("/api/v1/discover", json={"genres": ["action"], "availability_required": True, "region": "US"})

    assert response.status_code == 422
    assert response.json()["detail"] == {"error": "unsupported_filter", "filter": "availability_required"}
    app.dependency_overrides.clear()


def test_discovery_api_provider_failure_returns_safe_502_without_secret_leakage(monkeypatch):
    async def fake_discover(self, *, request):
        raise RuntimeError("TMDB request failed")

    monkeypatch.setattr(LookupService, "discover_movies", fake_discover)
    app.dependency_overrides[get_db] = lambda: DummyDb()
    client = TestClient(app)
    response = client.post("/api/v1/discover", json={"genres": ["action"]})

    assert response.status_code == 502
    assert response.json()["detail"] == "TMDB request failed"
    assert "token" not in response.text.lower()
    assert "bearer" not in response.text.lower()
    app.dependency_overrides.clear()
