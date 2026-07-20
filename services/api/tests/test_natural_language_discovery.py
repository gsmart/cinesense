import asyncio
import uuid

import pytest
from sqlalchemy.orm import Session

from app.schemas.natural_language import NaturalLanguageDiscoveryRequest
from app.services import LookupService
from tests.test_discovery_pipeline import SpyTmdb, make_session


class FakeInterpreter:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    async def interpret(self, request):
        self.calls += 1
        return self.payload


class RaisingInterpreter:
    async def interpret(self, request):
        raise RuntimeError("boom")


def make_service(session: Session | None = None) -> LookupService:
    return LookupService(session or make_session(), SpyTmdb())


def make_input(**overrides) -> NaturalLanguageDiscoveryRequest:
    payload = {"query": "  Marathi thrillers released between 2016 and 2018  "}
    payload.update(overrides)
    return NaturalLanguageDiscoveryRequest.model_validate(payload)


def test_valid_interpretation_succeeds_and_preserves_backend_order_without_recalculation(monkeypatch):
    service = make_service()
    first_id = str(uuid.uuid4())
    second_id = str(uuid.uuid4())
    calls = []

    async def fake_discover(*, request):
        calls.append(request)
        return {
            "status": "ok",
            "results": [
                {
                    "movie": {
                        "movie_id": first_id,
                        "canonical_title": "First",
                        "release_year": 2018,
                        "media_type": "movie",
                        "original_language": "mr",
                        "overview": "one",
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
                },
                {
                    "movie": {
                        "movie_id": second_id,
                        "canonical_title": "Second",
                        "release_year": 2017,
                        "media_type": "movie",
                        "original_language": "mr",
                        "overview": "two",
                        "poster_url": None,
                    },
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
            "page": {"page": 1, "requested_page_size": 20, "returned_count": 2, "max_page_size": 20},
        }

    monkeypatch.setattr(service, "discover_movies", fake_discover)
    interpreter = FakeInterpreter(
        {
            "genres": [" Thriller "],
            "original_language": " MR ",
            "release_year_min": 2016,
            "release_year_max": 2018,
            "page": 99,
            "page_size": 1,
        }
    )

    result = asyncio.run(service.discover_from_natural_language(request=make_input(), interpreter=interpreter))

    assert result["status"] == "ok"
    assert result["query"] == "Marathi thrillers released between 2016 and 2018"
    assert result["request"] == {
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
        "page_size": 20,
        "include_shadow": False,
    }
    assert len(calls) == 1
    assert calls[0].genres == ["thriller"]
    assert calls[0].page == 1
    assert calls[0].page_size == 20
    assert [item["tmdb_source_movie_id"] for item in result["results"]] == ["101", "202"]
    assert result["results"][0]["score"] == 80.0
    assert result["results"][0]["score_components"] == {"query_match": 30.0}


def test_equivalent_output_normalizes_identically_to_manual_request(monkeypatch):
    service = make_service()

    async def fake_discover(*, request):
        return {"status": "ok", "results": [], "page": {"page": request.page, "requested_page_size": request.page_size, "returned_count": 0, "max_page_size": 20}}

    monkeypatch.setattr(service, "discover_movies", fake_discover)
    interpreter = FakeInterpreter(
        {
            "genres": ["thriller", " Thriller "],
            "original_language": "MR",
            "release_year_min": 2016,
            "release_year_max": 2018,
        }
    )

    first = asyncio.run(service.discover_from_natural_language(request=make_input(), interpreter=interpreter))
    second = asyncio.run(
        service.discover_from_natural_language(
            request=make_input(page=2, page_size=2),
            interpreter=FakeInterpreter(
                {
                    "genres": [" thriller "],
                    "original_language": " mr ",
                    "release_year_min": 2016,
                    "release_year_max": 2018,
                }
            ),
        )
    )

    assert first["request"]["genres"] == ["thriller"]
    assert first["request"]["original_language"] == "mr"
    assert second["request"]["genres"] == ["thriller"]
    assert second["request"]["original_language"] == "mr"
    assert second["request"]["page"] == 2
    assert second["request"]["page_size"] == 2


@pytest.mark.parametrize(
    ("payload", "expected_status"),
    [
        ('{"genres":["thriller"],"original_language":"mr","release_year_min":2016,"release_year_max":2018}', "ok"),
        ("{", "invalid_interpretation"),
        (["thriller"], "invalid_interpretation"),
        ({"genres": ["unknown"]}, "invalid_interpretation"),
        ({"genres": ["thriller"], "original_language": "eng"}, "invalid_interpretation"),
        ({"genres": ["thriller"], "region": "usa"}, "invalid_interpretation"),
        ({"genres": ["thriller"], "release_year_min": 2019, "release_year_max": 2018}, "invalid_interpretation"),
        ({"genres": ["thriller"], "runtime_minutes_min": 120, "runtime_minutes_max": 90}, "invalid_interpretation"),
        ({}, "unrestricted_interpretation"),
        ({"region": "US"}, "unrestricted_interpretation"),
        ({"minimum_evidence_count": 0}, "unrestricted_interpretation"),
        ({"genres": ["thriller"], "tmdb_genre_ids": [53]}, "invalid_interpretation"),
        ({"genres": ["thriller"], "sort_by": "popularity.desc"}, "invalid_interpretation"),
        ({"genres": ["thriller"], "user_id": "123"}, "invalid_interpretation"),
        ({"genres": ["thriller"], "ranking_weights": {"popularity": 1}}, "invalid_interpretation"),
    ],
)
def test_invalid_and_unrestricted_interpretations_fail_safely_without_discovery(monkeypatch, payload, expected_status):
    service = make_service()
    calls = 0

    async def fake_discover(*, request):
        nonlocal calls
        calls += 1
        return {"status": "ok", "results": [], "page": {"page": 1, "requested_page_size": 20, "returned_count": 0, "max_page_size": 20}}

    monkeypatch.setattr(service, "discover_movies", fake_discover)
    result = asyncio.run(
        service.discover_from_natural_language(
            request=make_input(),
            interpreter=FakeInterpreter(payload),
        )
    )

    assert result["status"] == expected_status
    assert calls == (1 if expected_status == "ok" else 0)


def test_interpreter_exception_returns_controlled_failure_without_discovery(monkeypatch):
    service = make_service()
    calls = 0

    async def fake_discover(*, request):
        nonlocal calls
        calls += 1
        return {"status": "ok", "results": [], "page": {"page": 1, "requested_page_size": 20, "returned_count": 0, "max_page_size": 20}}

    monkeypatch.setattr(service, "discover_movies", fake_discover)
    result = asyncio.run(service.discover_from_natural_language(request=make_input(), interpreter=RaisingInterpreter()))

    assert result["status"] == "interpreter_failure"
    assert calls == 0


def test_availability_required_preserves_controlled_unsupported_filter(monkeypatch):
    service = make_service()

    async def fake_discover(*, request):
        assert request.availability_required is True
        assert request.region == "IN"
        return {
            "status": "unsupported_filter",
            "unsupported_filter": "availability_required",
            "results": [],
            "page": {"page": 1, "requested_page_size": 20, "returned_count": 0, "max_page_size": 20},
        }

    monkeypatch.setattr(service, "discover_movies", fake_discover)
    result = asyncio.run(
        service.discover_from_natural_language(
            request=make_input(),
            interpreter=FakeInterpreter({"genres": ["thriller"], "region": "in", "availability_required": True}),
        )
    )

    assert result["status"] == "unsupported_filter"
    assert result["unsupported_filter"] == "availability_required"
    assert result["request"]["availability_required"] is True


def test_repeated_valid_inputs_with_identical_interpreter_output_are_deterministic(monkeypatch):
    service = make_service()

    async def fake_discover(*, request):
        return {
            "status": "ok",
            "results": [{"tmdb_source_movie_id": "101", "score": 80.0, "score_components": {"query_match": 30.0}}],
            "page": {"page": request.page, "requested_page_size": request.page_size, "returned_count": 1, "max_page_size": 20},
        }

    monkeypatch.setattr(service, "discover_movies", fake_discover)
    interpreter_payload = {"genres": ["thriller"], "original_language": "mr", "release_year_min": 2016, "release_year_max": 2018}

    first = asyncio.run(
        service.discover_from_natural_language(request=make_input(page=2, page_size=2), interpreter=FakeInterpreter(interpreter_payload))
    )
    second = asyncio.run(
        service.discover_from_natural_language(request=make_input(page=2, page_size=2), interpreter=FakeInterpreter(interpreter_payload))
    )

    assert first == second


def test_natural_language_discovery_region_propagation(monkeypatch):
    service = make_service()
    calls = []

    async def fake_discover(*, request):
        calls.append(request)
        return {
            "status": "ok",
            "results": [],
            "page": {"page": 1, "requested_page_size": 20, "returned_count": 0, "max_page_size": 20},
        }

    monkeypatch.setattr(service, "discover_movies", fake_discover)
    interpreter_payload = {"genres": ["thriller"]}

    # Try region propagation
    result = asyncio.run(
        service.discover_from_natural_language(
            request=make_input(region="IN"),
            interpreter=FakeInterpreter(interpreter_payload),
        )
    )

    assert result["status"] == "ok"
    assert len(calls) == 1
    assert calls[0].region == "IN"

    # Verify schema validation on invalid region
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        NaturalLanguageDiscoveryRequest(query="test", region="INVALID")
