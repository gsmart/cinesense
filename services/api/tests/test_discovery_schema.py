from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.discovery import DiscoveryRequest


def test_discovery_request_normalizes_equivalent_inputs_deterministically() -> None:
    request = DiscoveryRequest(
        genres=[" Drama ", "comedy", "drama", " COMEDY "],
        original_language=" EN ",
        region=" us ",
        availability_required=True,
        minimum_evidence_count=3,
        release_year_min=1990,
        release_year_max=2000,
        runtime_minutes_min=90,
        runtime_minutes_max=120,
        page=2,
        page_size=5,
    )

    assert request.model_dump() == {
        "media_type": "movie",
        "genres": ["comedy", "drama"],
        "original_language": "en",
        "region": "US",
        "release_year_min": 1990,
        "release_year_max": 2000,
        "runtime_minutes_min": 90,
        "runtime_minutes_max": 120,
        "minimum_evidence_count": 3,
        "availability_required": True,
        "page": 2,
        "page_size": 5,
    }


def test_discovery_request_accepts_minimal_valid_narrowed_request() -> None:
    request = DiscoveryRequest(genres=["action"])

    assert request.media_type == "movie"
    assert request.genres == ["action"]
    assert request.original_language is None
    assert request.region is None
    assert request.release_year_min is None
    assert request.release_year_max is None
    assert request.runtime_minutes_min is None
    assert request.runtime_minutes_max is None
    assert request.minimum_evidence_count == 0
    assert request.availability_required is False
    assert request.page == 1
    assert request.page_size == 20


def test_discovery_request_normalizes_two_letter_original_language_to_lowercase() -> None:
    request = DiscoveryRequest(original_language=" HI ")

    assert request.original_language == "hi"


def test_discovery_request_rejects_invalid_ranges() -> None:
    with pytest.raises(ValidationError):
        DiscoveryRequest(genres=["action"], release_year_min=2001, release_year_max=2000)

    with pytest.raises(ValidationError):
        DiscoveryRequest(genres=["action"], runtime_minutes_min=121, runtime_minutes_max=120)


def test_discovery_request_rejects_unsupported_genres() -> None:
    with pytest.raises(ValidationError):
        DiscoveryRequest(genres=["superhero"])


def test_discovery_request_rejects_malformed_language_and_region_codes() -> None:
    with pytest.raises(ValidationError):
        DiscoveryRequest(genres=["action"], original_language="e1")

    with pytest.raises(ValidationError):
        DiscoveryRequest(genres=["action"], original_language="eng")

    with pytest.raises(ValidationError):
        DiscoveryRequest(genres=["action"], region="U1", availability_required=True)


def test_discovery_request_rejects_availability_without_region() -> None:
    with pytest.raises(ValidationError):
        DiscoveryRequest(availability_required=True, genres=["action"])


def test_discovery_request_rejects_unrestricted_requests() -> None:
    with pytest.raises(ValidationError):
        DiscoveryRequest()

    with pytest.raises(ValidationError):
        DiscoveryRequest(region="US")

    with pytest.raises(ValidationError):
        DiscoveryRequest(minimum_evidence_count=0)


def test_discovery_request_schema_is_stable_for_structured_output() -> None:
    schema = DiscoveryRequest.model_json_schema()
    current_year_plus_one = datetime.now().year + 1
    release_year_min = schema["properties"]["release_year_min"]["anyOf"][0]
    release_year_max = schema["properties"]["release_year_max"]["anyOf"][0]
    runtime_minutes_min = schema["properties"]["runtime_minutes_min"]["anyOf"][0]
    runtime_minutes_max = schema["properties"]["runtime_minutes_max"]["anyOf"][0]

    assert schema["additionalProperties"] is False
    assert schema["properties"]["media_type"]["const"] == "movie"
    assert schema["properties"]["genres"]["type"] == "array"
    assert schema["properties"]["genres"]["items"]["type"] == "string"
    assert schema["properties"]["minimum_evidence_count"]["default"] == 0
    assert schema["properties"]["availability_required"]["default"] is False
    assert schema["properties"]["page"]["default"] == 1
    assert schema["properties"]["page_size"]["default"] == 20
    assert schema["properties"]["page_size"]["maximum"] == 20
    assert release_year_min["minimum"] == 1888
    assert release_year_min["maximum"] == current_year_plus_one
    assert release_year_max["minimum"] == 1888
    assert release_year_max["maximum"] == current_year_plus_one
    assert runtime_minutes_min["minimum"] == 1
    assert runtime_minutes_min["maximum"] == 400
    assert runtime_minutes_max["minimum"] == 1
    assert runtime_minutes_max["maximum"] == 400
