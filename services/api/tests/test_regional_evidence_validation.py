import csv
import hashlib
import inspect
import json
from pathlib import Path

import pytest

import app.regional_evidence_validation as rv
from app.regional_evidence import WIKIDATA_AMBIGUOUS, WIKIDATA_ERROR, WIKIDATA_EXACT, WIKIDATA_NONE
from app.regional_evidence_validation import (
    BLOCKED_BY_DATA_INTEGRITY,
    BLOCKED_BY_LOW_COVERAGE,
    EXACT_MATCH_WITH_WARNINGS,
    GO_FOR_EXPANDED_SAMPLE,
    GO_WITH_WARNINGS,
    MANUAL_REVIEW_REQUIRED,
    SOURCE_ERROR,
    VALIDATED_EXACT_MATCH,
    ValidationThresholds,
    validate_regional_evidence_run,
)


def movie_record(
    tmdb_id: str,
    title: str,
    *,
    requested_language: str = "mr",
    original_language: str | None = None,
    release_year: int | None = 2020,
) -> dict:
    return {
        "source_name": "tmdb",
        "source_record_id": tmdb_id,
        "source_url": f"https://www.themoviedb.org/movie/{tmdb_id}",
        "fetched_at": "2026-07-19T00:00:00+00:00",
        "raw_response_hash": f"tmdb-{tmdb_id}",
        "parser_version": "regional-evidence-v1",
        "match_status": "COLLECTED",
        "warnings": [],
        "requested_language": requested_language,
        "provider_position": 0,
        "provider_page": 1,
        "provider_page_position": 0,
        "title": title,
        "original_title": title,
        "normalized_title": rv.normalize_evidence_title(title),
        "original_language": original_language or requested_language,
        "release_date": f"{release_year}-01-01" if release_year else None,
        "release_year": release_year,
        "genre_ids": [18],
        "popularity": 12.0,
        "vote_average": 7.1,
        "vote_count": 100,
    }


def wikidata_record(
    tmdb_id: str,
    *,
    match_status: str = WIKIDATA_EXACT,
    qid: str | None = None,
    english_label: str | None = None,
    native_label: str | None = None,
    native_language: str = "mr",
    aliases: list[str] | None = None,
    imdb_id: str | None = "tt1234567",
    countries: list[str] | None = None,
    directors: list[str] | None = None,
    original_languages: list[str] | None = None,
    publication_date: str | None = "2020-01-01T00:00:00Z",
) -> dict:
    titles = []
    if english_label:
        titles.append({"language": "en", "value": english_label, "normalized": rv.normalize_evidence_title(english_label)})
    if native_label:
        titles.append(
            {
                "language": native_language,
                "value": native_label,
                "normalized": rv.normalize_evidence_title(native_label),
            }
        )
    alternate_titles = [
        {"language": native_language, "value": alias, "normalized": rv.normalize_evidence_title(alias)}
        for alias in (aliases or [])
    ]
    language_names = {
        "mr": "Marathi",
        "ml": "Malayalam",
        "ta": "Tamil",
        "te": "Telugu",
        "kn": "Kannada",
        "hi": "Hindi",
        "en": "English",
    }
    return {
        "tmdb_source_movie_id": tmdb_id,
        "source_name": "wikidata",
        "source_record_id": qid or tmdb_id,
        "source_url": f"https://www.wikidata.org/wiki/{qid}" if qid else None,
        "fetched_at": "2026-07-19T00:00:00+00:00",
        "raw_response_hash": f"wikidata-{tmdb_id}",
        "parser_version": "regional-evidence-v1",
        "match_status": match_status,
        "warnings": [],
        "wikidata_qid": qid,
        "english_label": english_label,
        "titles": titles,
        "alternate_titles": alternate_titles,
        "imdb_id": imdb_id,
        "original_languages": original_languages if original_languages is not None else [language_names.get(native_language, native_language)],
        "countries_of_origin": countries if countries is not None else ["India"],
        "directors": directors if directors is not None else ["Director A"],
        "publication_date": publication_date,
    }


def write_run_dir(
    tmp_path: Path,
    *,
    run_id: str = "20260719T131728Z",
    movies: list[dict] | None = None,
    wikidata_matches: list[dict] | None = None,
    requested_languages: list[str] | None = None,
    output_hash_overrides: dict[str, str] | None = None,
    manifest_record_count_overrides: dict[str, int] | None = None,
    malformed_jsonl_file: str | None = None,
    malformed_json_file: str | None = None,
    include_optional: bool = True,
    secret_in_file: str | None = None,
) -> Path:
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    movies = movies or [movie_record("1", "Sairat")]
    wikidata_matches = wikidata_matches or [
        wikidata_record("1", qid="Q1", english_label="Sairat", native_label="सैराट", aliases=["Sairat"])
    ]
    requested_languages = requested_languages or sorted({movie["requested_language"] for movie in movies})
    coverage_summary = {"per_language": {}, "total": {"requested_languages": requested_languages}}
    awards_records: list[dict] = []
    recognition_records: list[dict] = []

    files = {
        "movies.jsonl": "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in movies) + "\n",
        "wikidata_matches.jsonl": "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in wikidata_matches) + "\n",
        "coverage_summary.json": json.dumps(coverage_summary, indent=2, sort_keys=True),
        "national_awards_records.jsonl": "\n".join(json.dumps(row, sort_keys=True) for row in awards_records),
        "recognition_match_candidates.jsonl": "\n".join(json.dumps(row, sort_keys=True) for row in recognition_records),
    }
    for name, content in files.items():
        if not include_optional and name in {"national_awards_records.jsonl", "recognition_match_candidates.jsonl"}:
            continue
        path = run_dir / name
        if malformed_jsonl_file == name:
            path.write_text("{bad-json\n", encoding="utf-8")
        elif malformed_json_file == name:
            path.write_text("{bad-json\n", encoding="utf-8")
        else:
            path.write_text(content, encoding="utf-8")

    if secret_in_file:
        secret_path = run_dir / secret_in_file
        if secret_in_file.endswith(".json"):
            secret_path.write_text(
                json.dumps({"debug": "Authorization: Bearer supersecret12345"}, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        else:
            secret_path.write_text(
                json.dumps({"debug": "Authorization: Bearer supersecret12345"}, sort_keys=True) + "\n",
                encoding="utf-8",
            )

    output_hashes = {}
    for name in ("movies.jsonl", "wikidata_matches.jsonl", "coverage_summary.json"):
        output_hashes[name] = hashlib.sha256((run_dir / name).read_bytes()).hexdigest()
    if include_optional:
        for name in ("national_awards_records.jsonl", "recognition_match_candidates.jsonl"):
            output_hashes[name] = hashlib.sha256((run_dir / name).read_bytes()).hexdigest()
    if output_hash_overrides:
        output_hashes.update(output_hash_overrides)

    manifest = {
        "run_id": run_id,
        "requested_languages": requested_languages,
        "limit_per_language": 50,
        "record_counts": {
            "movies": len(movies),
            "wikidata_matches": len(wikidata_matches),
            "national_awards_records": 0,
            "recognition_match_candidates": 0,
        },
        "error_counts": {},
        "output_hashes": output_hashes,
        "warnings": [],
    }
    if manifest_record_count_overrides:
        manifest["record_counts"].update(manifest_record_count_overrides)
    manifest_path = run_dir / "run_manifest.json"
    if malformed_json_file == "run_manifest.json":
        manifest_path.write_text("{bad-json\n", encoding="utf-8")
    else:
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return run_dir


def test_validate_run_directory_and_outputs_are_created(tmp_path):
    run_dir = write_run_dir(tmp_path)

    result = validate_regional_evidence_run(run_dir=run_dir)

    output_dir = run_dir / "validation"
    assert result["final_recommendation"] == GO_FOR_EXPANDED_SAMPLE
    assert output_dir.exists()
    assert (output_dir / "validated_matches.jsonl").exists()
    assert (output_dir / "validation_summary.json").exists()
    assert (output_dir / "review_sample.csv").exists()
    assert (output_dir / "validation_manifest.json").exists()
    assert result["validation_summary"]["coverage"]["aggregate"]["complete_identity_coverage"]["count"] == 1


def test_missing_required_file_and_malformed_inputs_fail_fast(tmp_path):
    run_dir = write_run_dir(tmp_path)
    (run_dir / "movies.jsonl").unlink()
    with pytest.raises(FileNotFoundError):
        validate_regional_evidence_run(run_dir=run_dir)

    malformed_jsonl_dir = write_run_dir(tmp_path, run_id="20260719T131729Z", malformed_jsonl_file="movies.jsonl")
    with pytest.raises(ValueError, match="invalid jsonl"):
        validate_regional_evidence_run(run_dir=malformed_jsonl_dir)

    malformed_json_dir = write_run_dir(tmp_path, run_id="20260719T131730Z", malformed_json_file="coverage_summary.json")
    with pytest.raises(ValueError, match="invalid json"):
        validate_regional_evidence_run(run_dir=malformed_json_dir)


def test_integrity_failures_cover_manifest_counts_hashes_duplicates_and_unknown_tmdb(tmp_path):
    movies = [movie_record("1", "Sairat"), movie_record("1", "Duplicate")]
    wikidata_matches = [
        wikidata_record("1", qid="Q1", english_label="Sairat", native_label="सैराट", aliases=["Sairat"]),
        wikidata_record("999", qid="Q999", english_label="Ghost", native_label="घोस्ट", aliases=["Ghost"]),
    ]
    run_dir = write_run_dir(
        tmp_path,
        run_id="20260719T131731Z",
        movies=movies,
        wikidata_matches=wikidata_matches,
        output_hash_overrides={"movies.jsonl": "bad-hash"},
        manifest_record_count_overrides={"movies": 3},
    )

    result = validate_regional_evidence_run(run_dir=run_dir)

    assert result["final_recommendation"] == BLOCKED_BY_DATA_INTEGRITY
    assert "manifest_count_mismatch:movies" in result["context"].integrity_errors
    assert "manifest_hash_mismatch:movies.jsonl" in result["context"].integrity_errors
    assert "duplicate_tmdb_movie_ids" in result["context"].integrity_errors
    assert "wikidata_record_unknown_tmdb_id:999" in result["context"].integrity_errors


@pytest.mark.parametrize(
    ("wikidata", "expected_classification", "expected_warning"),
    [
        (
            wikidata_record("1", qid="Q1", english_label="Sairat", native_label="सैराट", aliases=["Sairat"]),
            VALIDATED_EXACT_MATCH,
            None,
        ),
        (
            wikidata_record("1", qid="Q1", english_label="Sairat", native_label="सैराट", aliases=[]),
            EXACT_MATCH_WITH_WARNINGS,
            "MISSING_ALIASES",
        ),
        (
            {**wikidata_record("2", qid="Q2", english_label="Court", native_label="कोर्ट", aliases=["Court"]), "wikidata_tmdb_id": "999"},
            "AMBIGUOUS_REVIEW_REQUIRED",
            "TMDB_ID_CONFLICT",
        ),
        (
            wikidata_record("3", qid="Q3", english_label="Killa", native_label="किल्ला", aliases=["Killa"], publication_date="2019-01-01T00:00:00Z"),
            "AMBIGUOUS_REVIEW_REQUIRED",
            "YEAR_CONFLICT",
        ),
        (
            wikidata_record("4", qid="Q4", english_label="Fandry", native_label="फँड्री", aliases=["Fandry"], original_languages=["Hindi"]),
            "AMBIGUOUS_REVIEW_REQUIRED",
            "LANGUAGE_CONFLICT",
        ),
        (
            wikidata_record("5", match_status=WIKIDATA_NONE, qid=None, english_label=None, native_label=None, aliases=[]),
            "NO_MATCH",
            None,
        ),
        (
            wikidata_record("6", match_status=WIKIDATA_AMBIGUOUS, qid=None, english_label=None, native_label=None, aliases=[]),
            "AMBIGUOUS_REVIEW_REQUIRED",
            "MISSING_WIKIDATA_QID",
        ),
        (
            wikidata_record("7", match_status=WIKIDATA_ERROR, qid=None, english_label=None, native_label=None, aliases=[]),
            SOURCE_ERROR,
            None,
        ),
    ],
)
def test_match_classifications_and_warning_paths(tmp_path, wikidata, expected_classification, expected_warning):
    tmdb_id = wikidata["tmdb_source_movie_id"] if wikidata["tmdb_source_movie_id"] != "999" else "2"
    movies = [
        movie_record("1", "Sairat"),
        movie_record("2", "Court"),
        movie_record("3", "Killa"),
        movie_record("4", "Fandry"),
        movie_record("5", "Unknown"),
        movie_record("6", "Ambiguous"),
        movie_record("7", "Error"),
    ]
    movie_titles = {movie["source_record_id"]: movie["title"] for movie in movies}
    movie_for_case = next(movie for movie in movies if movie["source_record_id"] == tmdb_id)
    if expected_warning == "YEAR_CONFLICT":
        movie_for_case["release_year"] = 2020
    run_dir = write_run_dir(tmp_path, run_id=f"20260719T{tmdb_id.zfill(6)}Z", movies=[movie_for_case], wikidata_matches=[wikidata])

    result = validate_regional_evidence_run(run_dir=run_dir)
    match = result["validated_matches"][0]

    assert match["tmdb_title"] == movie_titles[tmdb_id]
    assert match["validation_classification"] == expected_classification
    if expected_warning:
        assert expected_warning in match["warnings"]


def test_complete_identity_and_per_language_coverage_metrics(tmp_path):
    movies = [
        movie_record("1", "Sairat", requested_language="mr"),
        movie_record("2", "Minnal", requested_language="ml"),
        movie_record("3", "No Match", requested_language="ml", release_year=None, original_language=None),
    ]
    wikidata_matches = [
        wikidata_record("1", qid="Q1", english_label="Sairat", native_label="सैराट", aliases=["Sairat"]),
            wikidata_record("2", qid="Q2", english_label="Minnal", native_label="മിന്നൽ", native_language="ml", aliases=[]),
        wikidata_record("3", match_status=WIKIDATA_NONE, qid=None, english_label=None, native_label=None, aliases=[]),
    ]
    run_dir = write_run_dir(
        tmp_path,
        run_id="20260719T131732Z",
        movies=movies,
        wikidata_matches=wikidata_matches,
        requested_languages=["mr", "ml"],
    )

    result = validate_regional_evidence_run(run_dir=run_dir)
    aggregate = result["validation_summary"]["coverage"]["aggregate"]
    per_language = result["validation_summary"]["coverage"]["per_language"]

    assert aggregate["validated_exact_matches"] == 1
    assert aggregate["exact_matches_with_warnings"] == 1
    assert aggregate["no_matches"] == 1
    assert aggregate["complete_identity_coverage"]["count"] == 2
    assert per_language["mr"]["validated_exact_matches"] == 1
    assert per_language["ml"]["exact_matches_with_warnings"] == 1
    assert per_language["ml"]["no_matches"] == 1


def test_review_sample_is_deterministic_balanced_and_supports_review_import(tmp_path):
    movies = [
        movie_record("1", "Sairat", requested_language="mr"),
        movie_record("2", "Minnal", requested_language="ml"),
        movie_record("3", "Unknown", requested_language="mr"),
        movie_record("4", "Error", requested_language="ml"),
    ]
    wikidata_matches = [
        wikidata_record("1", qid="Q1", english_label="Sairat", native_label="सैराट", aliases=["Sairat"]),
            wikidata_record("2", qid="Q2", english_label="Minnal", native_label="മിന്നൽ", native_language="ml", aliases=[]),
        wikidata_record("3", match_status=WIKIDATA_NONE, qid=None, english_label=None, native_label=None, aliases=[]),
        wikidata_record("4", match_status=WIKIDATA_ERROR, qid=None, english_label=None, native_label=None, aliases=[]),
    ]
    run_dir = write_run_dir(
        tmp_path,
        run_id="20260719T131733Z",
        movies=movies,
        wikidata_matches=wikidata_matches,
        requested_languages=["mr", "ml"],
    )

    first = validate_regional_evidence_run(run_dir=run_dir, review_sample_size=4)
    second = validate_regional_evidence_run(run_dir=run_dir, review_sample_size=4)
    first_rows = list(csv.DictReader((run_dir / "validation" / "review_sample.csv").open(encoding="utf-8")))
    second_rows = list(csv.DictReader((run_dir / "validation" / "review_sample.csv").open(encoding="utf-8")))
    assert first["validation_summary"]["classification_counts"] == second["validation_summary"]["classification_counts"]
    assert first_rows == second_rows
    assert {row["validation_classification"] for row in first_rows} >= {VALIDATED_EXACT_MATCH, EXACT_MATCH_WITH_WARNINGS, "NO_MATCH", SOURCE_ERROR}

    review_file = run_dir / "completed-review.csv"
    with review_file.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rv.REVIEW_SAMPLE_COLUMNS))
        writer.writeheader()
        writer.writerows(
            [
                {
                    "tmdb_movie_id": "1",
                    "wikidata_qid": "Q1",
                    "language": "mr",
                    "tmdb_title": "Sairat",
                    "tmdb_original_title": "Sairat",
                    "wikidata_label": "Sairat",
                    "wikidata_aliases": "Sairat",
                    "tmdb_release_year": "2020",
                    "wikidata_release_year": "2020",
                    "director": "Director A",
                    "country": "India",
                    "validation_classification": VALIDATED_EXACT_MATCH,
                    "warnings": "",
                    "reviewer_decision": "CONFIRMED",
                    "reviewer_notes": "",
                },
                {
                    "tmdb_movie_id": "2",
                    "wikidata_qid": "Q2",
                    "language": "ml",
                    "tmdb_title": "Minnal",
                    "tmdb_original_title": "Minnal",
                    "wikidata_label": "Minnal",
                    "wikidata_aliases": "",
                    "tmdb_release_year": "2020",
                    "wikidata_release_year": "2020",
                    "director": "Director A",
                    "country": "India",
                    "validation_classification": EXACT_MATCH_WITH_WARNINGS,
                    "warnings": "MISSING_ALIASES",
                    "reviewer_decision": "REJECTED",
                    "reviewer_notes": "",
                },
                {
                    "tmdb_movie_id": "3",
                    "wikidata_qid": "",
                    "language": "mr",
                    "tmdb_title": "Unknown",
                    "tmdb_original_title": "Unknown",
                    "wikidata_label": "",
                    "wikidata_aliases": "",
                    "tmdb_release_year": "",
                    "wikidata_release_year": "",
                    "director": "",
                    "country": "",
                    "validation_classification": "NO_MATCH",
                    "warnings": "",
                    "reviewer_decision": "NEEDS_FOLLOW_UP",
                    "reviewer_notes": "",
                },
            ]
        )
    reviewed = validate_regional_evidence_run(run_dir=run_dir, review_file=review_file)
    assert reviewed["review_stats"]["reviewed_count"] == 3
    assert reviewed["review_stats"]["confirmed_count"] == 1
    assert reviewed["review_stats"]["rejected_count"] == 1
    assert reviewed["review_stats"]["follow_up_count"] == 1
    assert reviewed["review_stats"]["confirmation_rate"] == pytest.approx(0.3333, abs=0.0001)

    invalid_review = run_dir / "invalid-review.csv"
    invalid_review.write_text(
        "tmdb_movie_id,wikidata_qid,language,tmdb_title,tmdb_original_title,wikidata_label,wikidata_aliases,tmdb_release_year,wikidata_release_year,director,country,validation_classification,warnings,reviewer_decision,reviewer_notes\n"
        "1,Q1,mr,Sairat,Sairat,Sairat,Sairat,2020,2020,Director A,India,VALIDATED_EXACT_MATCH,,MAYBE,\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid reviewer decision"):
        validate_regional_evidence_run(run_dir=run_dir, review_file=invalid_review)


def test_secret_detection_blocks_run(tmp_path):
    run_dir = write_run_dir(tmp_path, run_id="20260719T131734Z", secret_in_file="coverage_summary.json")

    result = validate_regional_evidence_run(run_dir=run_dir)

    assert result["final_recommendation"] == BLOCKED_BY_DATA_INTEGRITY
    assert result["context"].secret_findings == ["secret_pattern_detected:coverage_summary.json"]


def test_recommendation_thresholds_cover_warnings_manual_review_low_coverage_and_blocked(tmp_path):
    go_with_warnings_dir = write_run_dir(
        tmp_path,
        run_id="20260719T131735Z",
        movies=[movie_record("1", "Sairat"), movie_record("2", "Minnal", requested_language="ml", original_language="ml")],
        wikidata_matches=[
            wikidata_record("1", qid="Q1", english_label="Sairat", native_label="सैराट", aliases=["Sairat"]),
            wikidata_record("2", qid="Q2", english_label="Minnal", native_label="മിന്നൽ", native_language="ml", aliases=[]),
        ],
    )
    assert validate_regional_evidence_run(run_dir=go_with_warnings_dir)["final_recommendation"] == GO_WITH_WARNINGS

    manual_review_movies = [movie_record(str(index), f"Movie {index}") for index in range(1, 9)] + [movie_record("9", "Ambiguous")]
    manual_review_matches = [
        wikidata_record(str(index), qid=f"Q{index}", english_label=f"Movie {index}", native_label=f"Movie {index}", aliases=[f"Movie {index}"])
        for index in range(1, 9)
    ] + [wikidata_record("9", match_status=WIKIDATA_AMBIGUOUS, qid=None, english_label=None, native_label=None, aliases=[])]
    manual_review_dir = write_run_dir(
        tmp_path,
        run_id="20260719T131736Z",
        movies=manual_review_movies,
        wikidata_matches=manual_review_matches,
    )
    assert validate_regional_evidence_run(run_dir=manual_review_dir)["final_recommendation"] == MANUAL_REVIEW_REQUIRED

    low_coverage_dir = write_run_dir(
        tmp_path,
        run_id="20260719T131737Z",
        movies=[movie_record("1", "Sairat"), movie_record("2", "Missing"), movie_record("3", "Missing Too")],
        wikidata_matches=[
            wikidata_record("1", qid="Q1", english_label="Sairat", native_label="सैराट", aliases=["Sairat"]),
            wikidata_record("2", match_status=WIKIDATA_NONE, qid=None, english_label=None, native_label=None, aliases=[]),
            wikidata_record("3", match_status=WIKIDATA_NONE, qid=None, english_label=None, native_label=None, aliases=[]),
        ],
    )
    assert validate_regional_evidence_run(run_dir=low_coverage_dir)["final_recommendation"] == BLOCKED_BY_LOW_COVERAGE

    blocked_dir = write_run_dir(tmp_path, run_id="20260719T131738Z", output_hash_overrides={"movies.jsonl": "bad-hash"})
    assert validate_regional_evidence_run(run_dir=blocked_dir)["final_recommendation"] == BLOCKED_BY_DATA_INTEGRITY


def test_original_evidence_files_remain_unchanged_and_validator_stays_offline(tmp_path, monkeypatch):
    run_dir = write_run_dir(tmp_path, include_optional=False)
    before = {
        name: hashlib.sha256((run_dir / name).read_bytes()).hexdigest()
        for name in ("movies.jsonl", "wikidata_matches.jsonl", "coverage_summary.json", "run_manifest.json")
    }

    monkeypatch.setattr(
        "app.core.scoring.compute_cine_score_v1",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("scoring called")),
    )
    source = inspect.getsource(rv)

    result = validate_regional_evidence_run(run_dir=run_dir, thresholds=ValidationThresholds(strict=True))

    after = {
        name: hashlib.sha256((run_dir / name).read_bytes()).hexdigest()
        for name in ("movies.jsonl", "wikidata_matches.jsonl", "coverage_summary.json", "run_manifest.json")
    }
    assert before == after
    assert result["final_recommendation"] == GO_FOR_EXPANDED_SAMPLE
    assert "SessionLocal" not in source
    assert "get_db" not in source
    assert "compute_cine_score_v1" not in source
