import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.routes.lookup import get_db
from app.services import LookupService


class DummyDb:
    pass


def test_recommendations_api_valid_request_returns_seed_results_and_page_metadata(monkeypatch):
    seed_id = str(uuid.uuid4())

    async def fake_recommend(self, *, seed_movie_id, region=None, limit=20):
        assert seed_movie_id == seed_id
        assert region == "US"
        assert limit == 2
        return {
            "status": "ok",
            "seed": {
                "movie_id": seed_id,
                "canonical_title": "The Dark Knight",
                "release_year": 2008,
                "media_type": "movie",
            },
            "region": "US",
            "limit": 2,
            "results": [
                {
                    "movie": {
                        "movie_id": str(uuid.uuid4()),
                        "canonical_title": "Heat",
                        "release_year": 1995,
                        "media_type": "movie",
                        "original_language": "en",
                        "overview": "x",
                        "poster_url": "https://image.tmdb.org/t/p/w500/heat.jpg",
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
                "page": 1,
                "requested_page_size": 2,
                "returned_count": 1,
                "max_page_size": 20,
            },
        }

    monkeypatch.setattr(LookupService, "recommend_from_seed_movie", fake_recommend)
    app.dependency_overrides[get_db] = lambda: DummyDb()
    client = TestClient(app)

    response = client.post(
        "/api/v1/recommendations",
        json={"seed_movie_id": seed_id, "region": "US", "page_size": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["seed"]["movie_id"] == seed_id
    assert body["recommendations"][0]["tmdb_source_movie_id"] == "949"
    assert body["page"] == {
        "page": 1,
        "requested_page_size": 2,
        "returned_count": 1,
        "max_page_size": 20,
    }
    app.dependency_overrides.clear()


def test_recommendations_api_rejects_malformed_uuid():
    client = TestClient(app)
    response = client.post("/api/v1/recommendations", json={"seed_movie_id": "not-a-uuid"})
    assert response.status_code == 422


def test_recommendations_api_missing_seed_returns_404(monkeypatch):
    async def fake_recommend(self, *, seed_movie_id, region=None, limit=20):
        return {"status": "seed_not_found", "seed": None, "region": None, "limit": 20, "results": []}

    monkeypatch.setattr(LookupService, "recommend_from_seed_movie", fake_recommend)
    app.dependency_overrides[get_db] = lambda: DummyDb()
    client = TestClient(app)

    response = client.post("/api/v1/recommendations", json={"seed_movie_id": str(uuid.uuid4())})
    assert response.status_code == 404
    assert response.json()["detail"] == "Seed movie not found"
    app.dependency_overrides.clear()


def test_recommendations_api_unsupported_media_returns_422(monkeypatch):
    async def fake_recommend(self, *, seed_movie_id, region=None, limit=20):
        return {
            "status": "unsupported_media_type",
            "seed": {"movie_id": seed_movie_id, "canonical_title": "Seed", "release_year": 2000, "media_type": "series"},
            "region": None,
            "limit": 20,
            "results": [],
        }

    monkeypatch.setattr(LookupService, "recommend_from_seed_movie", fake_recommend)
    app.dependency_overrides[get_db] = lambda: DummyDb()
    client = TestClient(app)

    response = client.post("/api/v1/recommendations", json={"seed_movie_id": str(uuid.uuid4())})
    assert response.status_code == 422
    assert response.json()["detail"] == "Seed movie must have media type 'movie'"
    app.dependency_overrides.clear()


def test_recommendations_api_missing_tmdb_external_id_returns_422(monkeypatch):
    async def fake_recommend(self, *, seed_movie_id, region=None, limit=20):
        return {
            "status": "missing_external_id",
            "seed": {"movie_id": seed_movie_id, "canonical_title": "Seed", "release_year": 2000, "media_type": "movie"},
            "region": None,
            "limit": 20,
            "results": [],
        }

    monkeypatch.setattr(LookupService, "recommend_from_seed_movie", fake_recommend)
    app.dependency_overrides[get_db] = lambda: DummyDb()
    client = TestClient(app)

    response = client.post("/api/v1/recommendations", json={"seed_movie_id": str(uuid.uuid4())})
    assert response.status_code == 422
    assert response.json()["detail"] == "Seed movie does not have a TMDB external ID"
    app.dependency_overrides.clear()


def test_recommendations_api_rejects_page_size_out_of_range():
    client = TestClient(app)
    seed_id = str(uuid.uuid4())
    low = client.post("/api/v1/recommendations", json={"seed_movie_id": seed_id, "page_size": 0})
    high = client.post("/api/v1/recommendations", json={"seed_movie_id": seed_id, "page_size": 21})
    assert low.status_code == 422
    assert high.status_code == 422


def test_recommendations_api_empty_results_return_200(monkeypatch):
    seed_id = str(uuid.uuid4())

    async def fake_recommend(self, *, seed_movie_id, region=None, limit=20):
        return {
            "status": "ok",
            "seed": {"movie_id": seed_id, "canonical_title": "Seed", "release_year": 2000, "media_type": "movie"},
            "region": None,
            "limit": 20,
            "results": [],
            "page": {"page": 1, "requested_page_size": 20, "returned_count": 0, "max_page_size": 20},
        }

    monkeypatch.setattr(LookupService, "recommend_from_seed_movie", fake_recommend)
    app.dependency_overrides[get_db] = lambda: DummyDb()
    client = TestClient(app)
    response = client.post("/api/v1/recommendations", json={"seed_movie_id": seed_id})
    assert response.status_code == 200
    assert response.json()["recommendations"] == []
    app.dependency_overrides.clear()


def test_recommendations_api_provider_failure_returns_safe_502_without_secret_leakage(monkeypatch):
    async def fake_recommend(self, *, seed_movie_id, region=None, limit=20):
        raise RuntimeError("TMDB request failed")

    monkeypatch.setattr(LookupService, "recommend_from_seed_movie", fake_recommend)
    app.dependency_overrides[get_db] = lambda: DummyDb()
    client = TestClient(app)
    response = client.post("/api/v1/recommendations", json={"seed_movie_id": str(uuid.uuid4())})
    assert response.status_code == 502
    assert response.json()["detail"] == "TMDB request failed"
    assert "token" not in response.text.lower()
    assert "bearer" not in response.text.lower()
    app.dependency_overrides.clear()


def test_recommendations_api_preserves_orchestration_order_and_hides_raw_provider_payload(monkeypatch):
    seed_id = str(uuid.uuid4())
    first_id = str(uuid.uuid4())
    second_id = str(uuid.uuid4())

    async def fake_recommend(self, *, seed_movie_id, region=None, limit=20):
        return {
            "status": "ok",
            "seed": {"movie_id": seed_id, "canonical_title": "Seed", "release_year": 2000, "media_type": "movie"},
            "region": None,
            "limit": 20,
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

    monkeypatch.setattr(LookupService, "recommend_from_seed_movie", fake_recommend)
    app.dependency_overrides[get_db] = lambda: DummyDb()
    client = TestClient(app)
    response = client.post("/api/v1/recommendations", json={"seed_movie_id": seed_id})
    body = response.json()

    assert response.status_code == 200
    assert [item["tmdb_source_movie_id"] for item in body["recommendations"]] == ["101", "202"]
    assert "raw_payload" not in response.text
    assert "should" not in response.text
    app.dependency_overrides.clear()
