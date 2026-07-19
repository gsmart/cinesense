import asyncio
import csv
import json
from pathlib import Path

import httpx

from app.adapters.tmdb import TmdbCandidate
from app.core.config import Settings
from app.regional_evidence import (
    RECOGNITION_AMBIGUOUS,
    RECOGNITION_EXACT,
    RECOGNITION_NONE,
    WIKIDATA_AMBIGUOUS,
    WIKIDATA_ERROR,
    WIKIDATA_EXACT,
    WIKIDATA_NONE,
    RegionalEvidencePipeline,
    build_recognition_match_candidates,
    load_national_awards_records,
    normalize_evidence_title,
)


def make_settings() -> Settings:
    return Settings(TMDB_API_READ_ACCESS_TOKEN="super-secret-token")


def make_candidate(
    tmdb_id: str,
    title: str,
    *,
    original_language: str,
    provider_position: int,
    vote_average: float | None = 7.0,
    vote_count: int | None = 100,
    popularity: float | None = 10.0,
) -> TmdbCandidate:
    return TmdbCandidate(
        source_movie_id=tmdb_id,
        title=title,
        normalized_title=title.lower(),
        release_year=2020,
        release_date="2020-01-01",
        original_title=title,
        original_language=original_language,
        popularity=popularity,
        genre_ids=[18],
        vote_average=vote_average,
        vote_count=vote_count,
        rating_scale="0-10" if vote_average is not None else None,
        source_url=f"https://www.themoviedb.org/movie/{tmdb_id}",
        raw_response_hash=f"hash-{tmdb_id}",
        provider_position=provider_position,
    )


class FakeTmdb:
    enabled = True

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def discover_movies(self, request):
        key = (request.original_language, request.page)
        self.calls.append((request.original_language, request.page, request.page_size))
        value = self.pages.get(key, [])
        if isinstance(value, Exception):
            raise value
        return value


class FakeWikidata:
    def __init__(self, responses=None, errors=None):
        self.responses = responses or {}
        self.errors = {tuple(error) for error in (errors or [])}
        self.calls = []

    async def fetch_by_tmdb_ids(self, tmdb_ids):
        self.calls.append(list(tmdb_ids))
        if tuple(tmdb_ids) in self.errors:
            raise httpx.ConnectError("wikidata failed")
        rows = {}
        for tmdb_id in tmdb_ids:
            if tmdb_id in self.responses:
                rows[tmdb_id] = self.responses[tmdb_id]
        return rows, "wikidata-hash", "2026-07-19T00:00:00+00:00"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_tmdb_sampling_is_deterministic_enforces_limit_and_deduplicates(tmp_path):
    tmdb = FakeTmdb(
        {
            ("mr", 1): [
                make_candidate("1", "Movie One", original_language="mr", provider_position=0),
                make_candidate("2", "Movie Two", original_language="mr", provider_position=1),
            ],
            ("mr", 2): [
                make_candidate("2", "Movie Two", original_language="mr", provider_position=0),
                make_candidate("3", "Movie Three", original_language="mr", provider_position=1),
            ],
        }
    )
    pipeline = RegionalEvidencePipeline(settings=make_settings(), tmdb=tmdb, wikidata=FakeWikidata())

    manifest = asyncio.run(pipeline.build(languages=["mr"], limit_per_language=3, output_dir=tmp_path / "run"))

    movies = read_jsonl(tmp_path / "run" / "movies.jsonl")
    assert manifest["record_counts"]["movies"] == 3
    assert [movie["source_record_id"] for movie in movies] == ["1", "2", "3"]
    assert [movie["provider_position"] for movie in movies] == [0, 1, 2]
    assert tmdb.calls == [("mr", 1, 3), ("mr", 2, 1)]


def test_wikidata_matching_covers_exact_missing_ambiguous_and_source_error(tmp_path):
    tmdb = FakeTmdb(
        {
            ("mr", 1): [
                make_candidate("1", "Sairat", original_language="mr", provider_position=0),
                make_candidate("2", "Unknown", original_language="mr", provider_position=1),
                make_candidate("3", "Ambiguous", original_language="mr", provider_position=2),
            ]
        }
    )
    wikidata = FakeWikidata(
        responses={
            "1": [
                {
                    "item": {"value": "http://www.wikidata.org/entity/Q1"},
                    "tmdbId": {"value": "1"},
                    "label": {"value": "Sairat"},
                    "labelLang": {"value": "en"},
                    "altLabel": {"value": "सैराट"},
                    "altLang": {"value": "mr"},
                    "imdbId": {"value": "tt5312232"},
                    "languageLabel": {"value": "Marathi"},
                }
            ],
            "3": [
                {
                    "item": {"value": "http://www.wikidata.org/entity/Q3"},
                    "tmdbId": {"value": "3"},
                    "label": {"value": "Ambiguous A"},
                    "labelLang": {"value": "en"},
                },
                {
                    "item": {"value": "http://www.wikidata.org/entity/Q30"},
                    "tmdbId": {"value": "3"},
                    "label": {"value": "Ambiguous B"},
                    "labelLang": {"value": "en"},
                },
            ],
        }
    )
    pipeline = RegionalEvidencePipeline(settings=make_settings(), tmdb=tmdb, wikidata=wikidata)
    asyncio.run(pipeline.build(languages=["mr"], limit_per_language=3, output_dir=tmp_path / "run"))
    records = read_jsonl(tmp_path / "run" / "wikidata_matches.jsonl")
    by_id = {record["tmdb_source_movie_id"]: record for record in records}

    assert by_id["1"]["match_status"] == WIKIDATA_EXACT
    assert by_id["1"]["alternate_titles"][0]["normalized"] == normalize_evidence_title("सैराट")
    assert by_id["2"]["match_status"] == WIKIDATA_NONE
    assert by_id["3"]["match_status"] == WIKIDATA_AMBIGUOUS

    error_pipeline = RegionalEvidencePipeline(
        settings=make_settings(),
        tmdb=FakeTmdb({("mr", 1): [make_candidate("4", "Error Movie", original_language="mr", provider_position=0)]}),
        wikidata=FakeWikidata(errors=[("4",)]),
    )
    asyncio.run(error_pipeline.build(languages=["mr"], limit_per_language=1, output_dir=tmp_path / "error-run"))
    error_record = read_jsonl(tmp_path / "error-run" / "wikidata_matches.jsonl")[0]
    assert error_record["match_status"] == WIKIDATA_ERROR


def test_national_awards_csv_parsing_keeps_missing_fields_missing(tmp_path):
    csv_path = tmp_path / "awards.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["record_id", "title", "award", "year"])
        writer.writeheader()
        writer.writerow({"record_id": "1", "title": "Killa", "award": "Best Feature Film", "year": "2015"})

    records = load_national_awards_records(csv_path)

    assert len(records) == 1
    assert records[0].film_title == "Killa"
    assert records[0].award_name == "Best Feature Film"
    assert records[0].award_year == 2015
    assert records[0].language is None
    assert records[0].award_category is None


def test_recognition_matching_requires_year_and_language_and_never_accepts_title_only():
    movies = [
        {
            "source_record_id": "1",
            "normalized_title": normalize_evidence_title("Killa"),
            "release_year": 2015,
            "original_language": "mr",
        },
        {
            "source_record_id": "2",
            "normalized_title": normalize_evidence_title("Court"),
            "release_year": 2014,
            "original_language": "mr",
        },
        {
            "source_record_id": "3",
            "normalized_title": normalize_evidence_title("Court"),
            "release_year": 2015,
            "original_language": "hi",
        },
    ]
    awards = [
        {
            "source_name": "national_film_awards_ogd",
            "source_record_id": "a1",
            "source_url": "file:///awards.csv",
            "loaded_at": "2026-07-19T00:00:00+00:00",
            "raw_source_hash": "x",
            "parser_version": "regional-evidence-v1",
            "award_category": None,
            "award_name": "Best Film",
            "film_title": "Killa",
            "normalized_title": normalize_evidence_title("Killa"),
            "award_year": 2015,
            "language": "mr",
        },
        {
            "source_name": "national_film_awards_ogd",
            "source_record_id": "a2",
            "source_url": "file:///awards.csv",
            "loaded_at": "2026-07-19T00:00:00+00:00",
            "raw_source_hash": "y",
            "parser_version": "regional-evidence-v1",
            "award_category": None,
            "award_name": "Best Film",
            "film_title": "Court",
            "normalized_title": normalize_evidence_title("Court"),
            "award_year": None,
            "language": None,
        },
        {
            "source_name": "national_film_awards_ogd",
            "source_record_id": "a3",
            "source_url": "file:///awards.csv",
            "loaded_at": "2026-07-19T00:00:00+00:00",
            "raw_source_hash": "z",
            "parser_version": "regional-evidence-v1",
            "award_category": None,
            "award_name": "Best Film",
            "film_title": "Missing",
            "normalized_title": normalize_evidence_title("Missing"),
            "award_year": 2015,
            "language": "mr",
        },
    ]

    matches = build_recognition_match_candidates(awards_records=awards, movies=movies)
    by_id = {match["source_record_id"]: match for match in matches}

    assert by_id["a1"]["match_status"] == RECOGNITION_EXACT
    assert by_id["a2"]["match_status"] == RECOGNITION_AMBIGUOUS
    assert by_id["a3"]["match_status"] == RECOGNITION_NONE


def test_manifest_contains_hashes_and_partial_failures_preserve_outputs_and_secrets_absent(tmp_path, monkeypatch):
    tmdb = FakeTmdb(
        {
            ("mr", 1): [make_candidate("1", "Sairat", original_language="mr", provider_position=0)],
            ("ml", 1): httpx.ConnectError("network failed"),
        }
    )
    wikidata = FakeWikidata(errors=[("1",)])
    pipeline = RegionalEvidencePipeline(settings=make_settings(), tmdb=tmdb, wikidata=wikidata)
    monkeypatch.setattr("app.core.scoring.compute_cine_score_v1", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("scoring called")))
    monkeypatch.setattr("app.services.LookupService", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("service called")))

    manifest = asyncio.run(pipeline.build(languages=["mr", "ml"], limit_per_language=1, output_dir=tmp_path / "run"))

    assert (tmp_path / "run" / "movies.jsonl").exists()
    assert (tmp_path / "run" / "wikidata_matches.jsonl").exists()
    assert (tmp_path / "run" / "run_manifest.json").exists()
    assert manifest["error_counts"]["tmdb_errors"] == 1
    assert "movies.jsonl" in manifest["output_hashes"]
    assert "run_manifest.json" in manifest["output_hashes"]

    for path in (tmp_path / "run").iterdir():
        contents = path.read_text(encoding="utf-8")
        assert "super-secret-token" not in contents
