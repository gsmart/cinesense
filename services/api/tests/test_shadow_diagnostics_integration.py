import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

from app.main import app
from app.routes.lookup import get_db
from app.core.config import get_settings
from app.services import LookupService, load_regional_shadow_data


class DummyDb:
    pass


def test_shadow_diagnostics_disabled_by_default_returns_403(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "cinesense_enable_shadow_diagnostics", False)

    client = TestClient(app)

    response = client.post("/api/v1/lookup", json={
        "title": "Ved",
        "year": 2022,
        "region": "IN",
        "include_shadow": True
    })
    assert response.status_code == 403
    assert "Shadow diagnostics are disabled in this environment" in response.json()["detail"]


def test_shadow_diagnostics_enabled_with_eligible_and_ineligible_movies(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "cinesense_enable_shadow_diagnostics", True)
    monkeypatch.setattr(settings, "cinesense_shadow_run_id", "20260719T194508Z")

    fake_shadow_data = {
        "assignments": {
            "913544": {
                "tmdb_movie_id": "913544",
                "original_language": "mr",
                "selected_eligible_cohort_key": "language=mr",
                "selected_eligible_cohort_level": "level_3",
                "entity_resolution_status": "VALIDATED_EXACT_MATCH",
                "signal_values": {
                    "tmdb_rating_normalized": {"value": 0.65},
                    "tmdb_vote_count_log1p": {"value": 5.0},
                    "tmdb_popularity_log1p": {"value": 3.0},
                }
            }
        },
        "cohort_by_key": {
            "language=mr": {
                "cohort_key": "language=mr",
                "cohort_level": "level_3",
                "sample_count": 10,
                "eligible_for_normalization": True,
            }
        },
        "cohort_samples": {
            "language=mr": type("Samples", (), {
                "rating_normalized": (0.5, 0.6, 0.7),
                "vote_count_log1p": (4.0, 5.0, 6.0),
                "popularity_log1p": (2.0, 3.0, 4.0),
            })()
        },
        "baseline_hash": "dummy_hash_123",
        "review_status": "PENDING",
        "gate_status": "BLOCKED_BY_LOW_COVERAGE",
        "activation_eligible": False,
        "provisional_status": "PROVISIONAL_SHADOW_ONLY",
    }

    monkeypatch.setattr("app.services.load_regional_shadow_data", lambda *args, **kwargs: fake_shadow_data)

    from app.models.movie import Movie, Observation
    from datetime import datetime, UTC
    db_movie = Movie(
        canonical_title="Ved",
        normalized_title="ved",
        release_year=2022,
        original_language="mr",
    )
    db_movie.observations.append(
        Observation(
            source="tmdb",
            source_movie_id="913544",
            signal_type="audience_reception",
            numeric_value=6.5,
            evidence_count=100,
            fetched_at=datetime.now(UTC),
            raw_response_hash="hash"
        )
    )
    db_movie.observations.append(
        Observation(
            source="tmdb",
            source_movie_id="913544",
            signal_type="popularity",
            numeric_value=20.0,
            fetched_at=datetime.now(UTC),
            raw_response_hash="hash"
        )
    )
    monkeypatch.setattr(LookupService, "_find_tmdb_movie_by_source_id", lambda self, sid: db_movie if sid == "913544" else None)

    async def mock_lookup(self, *, title, year, region, media_type, include_shadow=False):
        results = [{
            "status": "resolved",
            "normalized_title": "ved",
            "region": "IN",
            "media_type": "movie",
            "source": "local_cache",
            "movie": {
                "movie_id": "some-uuid",
                "canonical_title": "Ved",
                "release_year": 2022,
                "media_type": "movie",
                "original_language": "mr",
                "overview": "desc",
                "runtime_minutes": None,
                "poster_url": None,
                "aliases": ["Ved"],
                "source": "local_cache",
                "source_movie_id": "913544",
                "source_url": None,
                "freshness": {},
                "observations": [],
                "missing_signals": [],
                "score": {
                    "version": "cine-score-v1",
                    "total": 60.5,
                    "components": {},
                    "missing_signals": [],
                }
            }
        }]
        self._attach_shadow_comparisons(results, include_shadow=include_shadow)
        return results[0]

    monkeypatch.setattr(LookupService, "lookup", mock_lookup)

    client = TestClient(app)

    response = client.post("/api/v1/lookup", json={
        "title": "Ved",
        "year": 2022,
        "region": "IN",
        "include_shadow": False
    })
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["movie"]["shadow_comparison"] is None

    response = client.post("/api/v1/lookup", json={
        "title": "Ved",
        "year": 2022,
        "region": "IN",
        "include_shadow": True
    })
    assert response.status_code == 200
    res_data = response.json()
    shadow = res_data["movie"]["shadow_comparison"]
    assert shadow is not None
    assert shadow["authoritative"] is False
    assert shadow["shadow_only"] is True
    assert shadow["v1_score"] == 60.5
    assert shadow["v2_score"] is not None
    assert shadow["review_status"] == "PENDING"
    assert shadow["activation_eligible"] is False
    assert shadow["ineligible_reason"] is None


def test_shadow_diagnostics_ineligible_movie(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "cinesense_enable_shadow_diagnostics", True)
    monkeypatch.setattr(settings, "cinesense_shadow_run_id", "20260719T194508Z")

    fake_shadow_data = {
        "assignments": {},
        "cohort_by_key": {},
        "cohort_samples": {},
        "baseline_hash": "dummy_hash_123",
        "review_status": "PENDING",
        "gate_status": "BLOCKED_BY_LOW_COVERAGE",
        "activation_eligible": False,
        "provisional_status": "PROVISIONAL_SHADOW_ONLY",
    }
    monkeypatch.setattr("app.services.load_regional_shadow_data", lambda *args, **kwargs: fake_shadow_data)
    monkeypatch.setattr(LookupService, "_find_tmdb_movie_by_source_id", lambda self, sid: None)

    async def mock_lookup(self, *, title, year, region, media_type, include_shadow=False):
        results = [{
            "status": "resolved",
            "normalized_title": "unknown",
            "region": "US",
            "media_type": "movie",
            "source": "local_cache",
            "movie": {
                "movie_id": "some-uuid",
                "canonical_title": "Unknown Movie",
                "release_year": 2020,
                "media_type": "movie",
                "original_language": "en",
                "overview": "desc",
                "runtime_minutes": None,
                "poster_url": None,
                "aliases": ["Unknown Movie"],
                "source": "local_cache",
                "source_movie_id": "999999",
                "source_url": None,
                "freshness": {},
                "observations": [],
                "missing_signals": [],
                "score": {
                    "version": "cine-score-v1",
                    "total": 50.0,
                    "components": {},
                    "missing_signals": [],
                }
            }
        }]
        self._attach_shadow_comparisons(results, include_shadow=include_shadow)
        return results[0]

    monkeypatch.setattr(LookupService, "lookup", mock_lookup)

    client = TestClient(app)
    response = client.post("/api/v1/lookup", json={
        "title": "Unknown Movie",
        "year": 2020,
        "region": "US",
        "include_shadow": True
    })
    assert response.status_code == 200
    res_data = response.json()
    shadow = res_data["movie"]["shadow_comparison"]
    assert shadow is not None
    assert shadow["ineligible_reason"] == "insufficient_live_signals"


def test_shadow_diagnostics_include_shadow_absent(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "cinesense_enable_shadow_diagnostics", True)

    async def mock_lookup(self, *, title, year, region, media_type, include_shadow=False):
        return {
            "status": "resolved",
            "normalized_title": "ved",
            "region": "IN",
            "media_type": "movie",
            "source": "local_cache",
            "movie": {
                "movie_id": "some-uuid",
                "canonical_title": "Ved",
                "release_year": 2022,
                "media_type": "movie",
                "original_language": "mr",
                "overview": "desc",
                "runtime_minutes": None,
                "poster_url": None,
                "aliases": ["Ved"],
                "source": "local_cache",
                "source_movie_id": "913544",
                "source_url": None,
                "freshness": {},
                "observations": [],
                "missing_signals": [],
                "score": {
                    "version": "cine-score-v1",
                    "total": 60.5,
                    "components": {},
                    "missing_signals": [],
                },
                "shadow_comparison": None
            }
        }
    monkeypatch.setattr(LookupService, "lookup", mock_lookup)

    client = TestClient(app)
    # Absent in payload, should default to False and not fail
    response = client.post("/api/v1/lookup", json={
        "title": "Ved",
        "year": 2022,
        "region": "IN"
    })
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["movie"]["shadow_comparison"] is None


def test_shadow_diagnostics_openapi_contract():
    client = TestClient(app)
    response = client.get("/openapi.json")
    assert response.status_code == 200
    openapi = response.json()

    # Check that LookupRequest includes include_shadow schema
    lookup_req_schema = openapi["components"]["schemas"]["LookupRequest"]
    assert "include_shadow" in lookup_req_schema["properties"]
    assert lookup_req_schema["properties"]["include_shadow"]["type"] == "boolean"
    assert lookup_req_schema["properties"]["include_shadow"].get("default") is False


def test_shadow_diagnostics_discover_and_recommendations_gating(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "cinesense_enable_shadow_diagnostics", False)

    client = TestClient(app)

    # Test structured discovery gating
    response = client.post("/api/v1/discover", json={
        "media_type": "movie",
        "genres": ["action"],
        "include_shadow": True
    })
    assert response.status_code == 403
    assert "Shadow diagnostics are disabled in this environment" in response.json()["detail"]

    # Test recommendations gating
    response = client.post("/api/v1/recommendations", json={
        "seed_movie_id": "00000000-0000-0000-0000-000000000000",
        "include_shadow": True
    })
    assert response.status_code == 403
    assert "Shadow diagnostics are disabled in this environment" in response.json()["detail"]

    # Test natural language discovery gating
    response = client.post("/api/v1/discover/natural-language", json={
        "query": "Marathi thrillers",
        "region": "IN",
        "include_shadow": True
    })
    assert response.status_code == 403
    assert "Shadow diagnostics are disabled in this environment" in response.json()["detail"]


def test_natural_language_discovery_region_support(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "cinesense_enable_shadow_diagnostics", True)
    monkeypatch.setattr(settings, "cinesense_shadow_run_id", "20260719T194508Z")

    class MockInterpreter:
        async def interpret(self, request):
            return {"genres": ["thriller"], "original_language": "mr"}

    async def fake_discover_movies(self, *, request):
        return {
            "status": "ok",
            "results": [],
            "page": {"page": request.page, "requested_page_size": request.page_size, "returned_count": 0, "max_page_size": 20}
        }

    import app.services as app_services
    monkeypatch.setattr(app_services, "load_regional_shadow_data", lambda *args, **kwargs: {})
    monkeypatch.setattr(LookupService, "discover_movies", fake_discover_movies)

    from app.routes.lookup import get_natural_language_discovery_interpreter
    app.dependency_overrides[get_natural_language_discovery_interpreter] = lambda: MockInterpreter()

    try:
        client = TestClient(app)
        response = client.post("/api/v1/discover/natural-language", json={
            "query": "Marathi thrillers",
            "region": "IN",
            "include_shadow": True
        })
        # Check that it parses correctly and doesn't return 422 validation error
        assert response.status_code == 200
        res_data = response.json()
        assert res_data["status"] == "ok"
    finally:
        if get_natural_language_discovery_interpreter in app.dependency_overrides:
            del app.dependency_overrides[get_natural_language_discovery_interpreter]


def test_shadow_diagnostics_movie_keying(monkeypatch, tmp_path):
    import json
    settings = get_settings()
    monkeypatch.setattr(settings, "cinesense_enable_shadow_diagnostics", True)
    # 1. Real artifact root pointing to workspace local-artifacts
    monkeypatch.setattr(settings, "cinesense_shadow_artifact_root", "/Users/ganeshsawant/Documents/work/cineSense/cinesense/.local-artifacts/regional-shadow")
    monkeypatch.setattr(settings, "cinesense_shadow_run_id", "20260719T194508Z")

    client = TestClient(app)

    from app.models.movie import Movie, Observation
    from datetime import datetime, UTC
    db_movie_ff = Movie(
        canonical_title="Faster Fene",
        normalized_title="faster fene",
        release_year=2017,
        original_language="mr",
    )
    db_movie_ff.observations.append(
        Observation(
            source="tmdb",
            source_movie_id="484038",
            signal_type="audience_reception",
            numeric_value=7.5,
            evidence_count=150,
            fetched_at=datetime.now(UTC),
            raw_response_hash="hash"
        )
    )
    db_movie_ff.observations.append(
        Observation(
            source="tmdb",
            source_movie_id="484038",
            signal_type="popularity",
            numeric_value=15.0,
            fetched_at=datetime.now(UTC),
            raw_response_hash="hash"
        )
    )

    def mock_find(self, sid):
        if sid == "484038":
            return db_movie_ff
        return None

    monkeypatch.setattr(LookupService, "_find_tmdb_movie_by_source_id", mock_find)

    # Mock lookup output structure for Faster Fene (TMDB ID 484038)
    async def mock_lookup(self, *, title, year, region, media_type, include_shadow=False):
        results = [{
            "status": "resolved",
            "normalized_title": "faster fene",
            "region": "IN",
            "media_type": "movie",
            "source": "local_cache",
            "movie": {
                "movie_id": "faster-fene-uuid",
                "canonical_title": "Faster Fene",
                "release_year": 2017,
                "media_type": "movie",
                "original_language": "mr",
                "overview": "desc",
                "runtime_minutes": 134,
                "poster_url": None,
                "aliases": ["Faster Fene"],
                "source": "local_cache",
                "source_movie_id": "484038",
                "source_url": None,
                "freshness": {},
                "observations": [],
                "missing_signals": [],
                "score": {
                    "version": "cine-score-v1",
                    "total": 64.96,
                    "components": {},
                    "missing_signals": [],
                }
            }
        }]
        self._attach_shadow_comparisons(results, include_shadow=include_shadow)
        return results[0]

    monkeypatch.setattr(LookupService, "lookup", mock_lookup)

    # 1. Proving TMDB ID 484038 is found and receives non-null v2 score
    response = client.post("/api/v1/lookup", json={
        "title": "Faster Fene",
        "year": 2017,
        "region": "IN",
        "include_shadow": True
    })
    assert response.status_code == 200
    res_data = response.json()
    shadow = res_data["movie"]["shadow_comparison"]
    assert shadow is not None
    assert shadow["v2_score"] is not None
    assert shadow["ineligible_reason"] is None

    # 2. Incorrect IDs return movie_not_in_regional_cohort_sample
    async def mock_lookup_incorrect(self, *, title, year, region, media_type, include_shadow=False):
        results = [{
            "status": "resolved",
            "normalized_title": "incorrect",
            "region": "IN",
            "media_type": "movie",
            "source": "local_cache",
            "movie": {
                "movie_id": "incorrect-uuid",
                "canonical_title": "Incorrect Movie",
                "release_year": 2017,
                "media_type": "movie",
                "original_language": "mr",
                "overview": "desc",
                "runtime_minutes": 100,
                "poster_url": None,
                "aliases": [],
                "source": "local_cache",
                "source_movie_id": "999999", # Incorrect TMDB ID
                "source_url": None,
                "freshness": {},
                "observations": [],
                "missing_signals": [],
                "score": {
                    "version": "cine-score-v1",
                    "total": 50.0,
                    "components": {},
                    "missing_signals": [],
                }
            }
        }]
        self._attach_shadow_comparisons(results, include_shadow=include_shadow)
        return results[0]

    monkeypatch.setattr(LookupService, "lookup", mock_lookup_incorrect)
    response = client.post("/api/v1/lookup", json={
        "title": "Incorrect Movie",
        "year": 2017,
        "region": "IN",
        "include_shadow": True
    })
    assert response.status_code == 200
    res_data = response.json()
    shadow = res_data["movie"]["shadow_comparison"]
    assert shadow is not None
    assert shadow["v2_score"] is None
    assert shadow["ineligible_reason"] == "insufficient_live_signals"

    # 3. Missing artifacts return a clear diagnostic reason (baseline_cohort_artifacts_not_found)
    monkeypatch.setattr(settings, "cinesense_shadow_artifact_root", "/non-existent-directory")
    monkeypatch.setattr(LookupService, "lookup", mock_lookup)
    response = client.post("/api/v1/lookup", json={
        "title": "Faster Fene",
        "year": 2017,
        "region": "IN",
        "include_shadow": True
    })
    assert response.status_code == 200
    res_data = response.json()
    shadow = res_data["movie"]["shadow_comparison"]
    assert shadow is not None
    assert shadow["v2_score"] is None
    assert shadow["ineligible_reason"] == "baseline_artifacts_not_found"

    # 4. Artifact version mismatch fails clearly (raises ValueError)
    run_dir = tmp_path / "20260719T194508Z"
    run_dir.mkdir()
    with open(run_dir / "cohort_baselines.json", "w") as f:
        json.dump({"baseline_version": "invalid-version"}, f)
    with open(run_dir / "movie_cohort_assignments.jsonl", "w") as f:
        f.write("\n")

    monkeypatch.setattr(settings, "cinesense_shadow_artifact_root", str(tmp_path))
    with pytest.raises(ValueError, match="baseline_cohort_version_mismatch"):
        client.post("/api/v1/lookup", json={
            "title": "Faster Fene",
            "year": 2017,
            "region": "IN",
            "include_shadow": True
        })


def test_shadow_diagnostics_dynamic_cohort_and_fallback(monkeypatch, tmp_path):
    settings = get_settings()
    monkeypatch.setattr(settings, "cinesense_enable_shadow_diagnostics", True)
    monkeypatch.setattr(settings, "cinesense_shadow_artifact_root", "/Users/ganeshsawant/Documents/work/cineSense/cinesense/.local-artifacts/regional-shadow")
    monkeypatch.setattr(settings, "cinesense_shadow_run_id", "20260719T194508Z")

    # Mock dynamic cohort lookup logic
    from app.models.movie import Movie, Observation
    from app.services import LookupService
    from datetime import datetime, UTC

    client = TestClient(app)

    async def mock_lookup_live(self, *, title, year, region, media_type, include_shadow=False):
        # Construct a mock DB Movie record for a non-sampled movie like Natsamrat
        db_movie = Movie(
            canonical_title="Natsamrat",
            normalized_title="natsamrat",
            release_year=2016,
            original_language="mr",
        )
        db_movie.observations.append(
            Observation(
                source="tmdb",
                source_movie_id="378227",
                signal_type="title_metadata",
                value={
                    "title": "Natsamrat",
                    "original_title": "Natsamrat",
                    "release_date": "2016-01-01",
                    "genre_ids": [18], # Drama
                },
                fetched_at=datetime.now(UTC),
                raw_response_hash="hash",
            )
        )
        db_movie.observations.append(
            Observation(
                source="tmdb",
                source_movie_id="378227",
                signal_type="audience_reception",
                value={"vote_average": 8.1, "vote_count": 250},
                numeric_value=8.1,
                evidence_count=250,
                fetched_at=datetime.now(UTC),
                raw_response_hash="hash",
            )
        )
        db_movie.observations.append(
            Observation(
                source="tmdb",
                source_movie_id="378227",
                signal_type="popularity",
                value={"popularity": 12.5},
                numeric_value=12.5,
                fetched_at=datetime.now(UTC),
                raw_response_hash="hash",
            )
        )

        # Mock database lookup to return this movie
        def mock_find(source_id):
            if source_id == "378227":
                return db_movie
            return None
        monkeypatch.setattr(self, "_find_tmdb_movie_by_source_id", mock_find)

        results = [{
            "status": "resolved",
            "normalized_title": "natsamrat",
            "region": "IN",
            "media_type": "movie",
            "source": "local_cache",
            "movie": {
                "movie_id": "natsamrat-uuid",
                "canonical_title": "Natsamrat",
                "release_year": 2016,
                "media_type": "movie",
                "original_language": "mr",
                "overview": "desc",
                "runtime_minutes": 166,
                "poster_url": None,
                "aliases": ["Natsamrat"],
                "source": "local_cache",
                "source_movie_id": "378227",
                "source_url": None,
                "freshness": {},
                "observations": [],
                "missing_signals": [],
                "score": {
                    "version": "cine-score-v1",
                    "total": 64.46,
                    "components": {},
                    "missing_signals": [],
                }
            }
        }]
        self._attach_shadow_comparisons(results, include_shadow=include_shadow)
        return results[0]

    monkeypatch.setattr(LookupService, "lookup", mock_lookup_live)

    # Proving Natsamrat (which is not in movie_cohort_assignments.jsonl) receives a non-null v2 score
    response = client.post("/api/v1/lookup", json={
        "title": "Natsamrat",
        "year": 2016,
        "region": "IN",
        "include_shadow": True
    })
    assert response.status_code == 200
    res_data = response.json()
    shadow = res_data["movie"]["shadow_comparison"]
    assert shadow is not None
    assert shadow["v2_score"] is not None
    assert shadow["ineligible_reason"] is None








