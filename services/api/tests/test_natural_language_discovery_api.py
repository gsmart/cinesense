import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.routes.lookup import get_db, get_natural_language_discovery_interpreter
from app.services import LookupService


class DummyDb:
    pass


class FakeInterpreter:
    async def interpret(self, request):
        return {"genres": ["thriller"], "original_language": "mr", "release_year_min": 2016, "release_year_max": 2018}


def valid_request():
    return {
        "query": "  Marathi thrillers released between 2016 and 2018  ",
        "page": 1,
        "page_size": 10,
    }


def test_natural_language_discovery_api_valid_request_returns_200(monkeypatch):
    first_id = str(uuid.uuid4())
    fake_interpreter = FakeInterpreter()

    async def fake_discover_from_natural_language(self, *, request, interpreter):
        assert interpreter is fake_interpreter
        assert request.query == "Marathi thrillers released between 2016 and 2018"
        return {
            "status": "ok",
            "query": request.query,
            "request": {
                "media_type": "movie",
                "genres": ["thriller"],
                "original_language": "mr",
                "region": None,
                "release_year_min": 2016,
                "release_year_max": 2018,
                "runtime_minutes_min": None,
                "runtime_minutes_max": None,
                "minimum_evidence_count": 0,
                "availability_required": False,
                "page": 1,
                "page_size": 10,
            },
            "results": [
                {
                    "movie": {
                        "movie_id": first_id,
                        "canonical_title": "First",
                        "release_year": 2018,
                        "media_type": "movie",
                        "original_language": "mr",
                        "overview": "x",
                        "poster_url": None,
                    },
                    "tmdb_source_movie_id": "101",
                    "provider_position": 0,
                    "score": 80.0,
                    "score_version": "cine-score-v1",
                    "score_components": {"query_match": 30.0},
                    "missing_signals": ["critic_consensus"],
                    "provenance": {"source": "tmdb", "source_movie_id": "101", "source_url": "https://www.themoviedb.org/movie/101"},
                    "freshness": {"critic_consensus": "MISSING"},
                    "raw_provider_payload": {"must": "not leak"},
                }
            ],
            "page": {"page": 1, "requested_page_size": 10, "returned_count": 1, "max_page_size": 20},
        }

    monkeypatch.setattr(LookupService, "discover_from_natural_language", fake_discover_from_natural_language)
    app.dependency_overrides[get_db] = lambda: DummyDb()
    app.dependency_overrides[get_natural_language_discovery_interpreter] = lambda: fake_interpreter
    client = TestClient(app)

    response = client.post("/api/v1/discover/natural-language", json=valid_request())

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "Marathi thrillers released between 2016 and 2018"
    assert body["interpreted_request"]["genres"] == ["thriller"]
    assert body["interpreted_request"]["original_language"] == "mr"
    assert body["page"] == {"page": 1, "requested_page_size": 10, "returned_count": 1, "max_page_size": 20}
    assert [item["tmdb_source_movie_id"] for item in body["results"]] == ["101"]
    assert body["results"][0]["score"] == 80.0
    assert "raw_provider_payload" not in response.text
    app.dependency_overrides.clear()


def test_natural_language_discovery_api_preserves_order_and_is_deterministic(monkeypatch):
    first_id = str(uuid.uuid4())
    second_id = str(uuid.uuid4())

    async def fake_discover_from_natural_language(self, *, request, interpreter):
        return {
            "status": "ok",
            "query": request.query,
            "request": {
                "media_type": "movie",
                "genres": ["thriller"],
                "original_language": "mr",
                "region": None,
                "release_year_min": 2016,
                "release_year_max": 2018,
                "runtime_minutes_min": None,
                "runtime_minutes_max": None,
                "minimum_evidence_count": 0,
                "availability_required": False,
                "page": 1,
                "page_size": 10,
            },
            "results": [
                {
                    "movie": {"movie_id": first_id, "canonical_title": "First", "release_year": 2018, "media_type": "movie", "original_language": "mr", "overview": "one", "poster_url": None},
                    "tmdb_source_movie_id": "101",
                    "provider_position": 0,
                    "score": 80.0,
                    "score_version": "cine-score-v1",
                    "score_components": {"query_match": 30.0},
                    "missing_signals": ["critic_consensus"],
                    "provenance": {"source": "tmdb", "source_movie_id": "101", "source_url": "https://www.themoviedb.org/movie/101"},
                    "freshness": {"critic_consensus": "MISSING"},
                },
                {
                    "movie": {"movie_id": second_id, "canonical_title": "Second", "release_year": 2017, "media_type": "movie", "original_language": "mr", "overview": "two", "poster_url": None},
                    "tmdb_source_movie_id": "202",
                    "provider_position": 1,
                    "score": 70.0,
                    "score_version": "cine-score-v1",
                    "score_components": {"query_match": 29.0},
                    "missing_signals": ["critic_consensus"],
                    "provenance": {"source": "tmdb", "source_movie_id": "202", "source_url": "https://www.themoviedb.org/movie/202"},
                    "freshness": {"critic_consensus": "MISSING"},
                },
            ],
            "page": {"page": 1, "requested_page_size": 10, "returned_count": 2, "max_page_size": 20},
        }

    monkeypatch.setattr(LookupService, "discover_from_natural_language", fake_discover_from_natural_language)
    app.dependency_overrides[get_db] = lambda: DummyDb()
    app.dependency_overrides[get_natural_language_discovery_interpreter] = lambda: FakeInterpreter()
    client = TestClient(app)

    first = client.post("/api/v1/discover/natural-language", json=valid_request())
    second = client.post("/api/v1/discover/natural-language", json=valid_request())

    assert first.status_code == 200
    assert [item["tmdb_source_movie_id"] for item in first.json()["results"]] == ["101", "202"]
    assert first.json()["results"] == second.json()["results"]
    app.dependency_overrides.clear()


def test_natural_language_discovery_api_empty_results_return_200(monkeypatch):
    async def fake_discover_from_natural_language(self, *, request, interpreter):
        return {
            "status": "ok",
            "query": request.query,
            "request": {
                "media_type": "movie",
                "genres": ["thriller"],
                "original_language": "mr",
                "region": None,
                "release_year_min": 2016,
                "release_year_max": 2018,
                "runtime_minutes_min": None,
                "runtime_minutes_max": None,
                "minimum_evidence_count": 0,
                "availability_required": False,
                "page": 1,
                "page_size": 10,
            },
            "results": [],
            "page": {"page": 1, "requested_page_size": 10, "returned_count": 0, "max_page_size": 20},
        }

    monkeypatch.setattr(LookupService, "discover_from_natural_language", fake_discover_from_natural_language)
    app.dependency_overrides[get_db] = lambda: DummyDb()
    app.dependency_overrides[get_natural_language_discovery_interpreter] = lambda: FakeInterpreter()
    client = TestClient(app)
    response = client.post("/api/v1/discover/natural-language", json=valid_request())

    assert response.status_code == 200
    assert response.json()["results"] == []
    app.dependency_overrides.clear()


def test_natural_language_discovery_api_malformed_request_returns_422():
    client = TestClient(app)
    response = client.post("/api/v1/discover/natural-language", json={"query": "   "})
    assert response.status_code == 422


def test_natural_language_discovery_api_maps_controlled_failures(monkeypatch):
    cases = [
        ("invalid_interpretation", 422, {"error": "invalid_interpretation"}),
        ("unrestricted_interpretation", 422, {"error": "unrestricted_interpretation"}),
        ("interpreter_unavailable", 503, {"error": "interpreter_unavailable"}),
        ("interpreter_failure", 502, {"error": "interpreter_failure"}),
        ("unsupported_filter", 422, {"error": "unsupported_filter", "filter": "availability_required"}),
    ]

    for status, expected_code, expected_detail in cases:
        async def fake_discover_from_natural_language(self, *, request, interpreter, status=status):
            result = {"status": status, "query": request.query}
            if status == "unsupported_filter":
                result["unsupported_filter"] = "availability_required"
            return result

        monkeypatch.setattr(LookupService, "discover_from_natural_language", fake_discover_from_natural_language)
        app.dependency_overrides[get_db] = lambda: DummyDb()
        app.dependency_overrides[get_natural_language_discovery_interpreter] = lambda: FakeInterpreter()
        client = TestClient(app)

        response = client.post("/api/v1/discover/natural-language", json=valid_request())

        assert response.status_code == expected_code
        assert response.json()["detail"] == expected_detail
        assert "secret" not in response.text
        app.dependency_overrides.clear()
