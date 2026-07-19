import csv
import hashlib
import json
from pathlib import Path

from app.regional_cohort_baselines import (
    DEFAULT_LEVEL_THRESHOLDS,
    PHASE_BLOCKED,
    PHASE_EXPAND,
    PHASE_PROCEED,
    PHASE_REVIEW,
    READINESS_ENTITY_BLOCKED,
    READINESS_INSUFFICIENT,
    READINESS_LIMITED,
    READINESS_READY,
    UNKNOWN_GENRE,
    UNKNOWN_YEAR,
    CohortBaselineConfig,
    assign_release_era,
    build_cohort_key,
    build_regional_cohort_baselines,
)


def movie_record(
    tmdb_id: int,
    *,
    language: str,
    title: str | None = None,
    normalized_title: str | None = None,
    release_year: int | None = 2016,
    genres: list[str] | None = None,
    vote_average: object = 7.0,
    vote_count: object = 100,
    popularity: object = 10.0,
    rating_scale: str | None = None,
) -> dict:
    title = title or f"Movie {tmdb_id}"
    return {
        "source_name": "tmdb",
        "source_record_id": str(tmdb_id),
        "title": title,
        "original_title": title,
        "normalized_title": normalized_title or title.casefold(),
        "requested_language": language,
        "original_language": language,
        "release_year": release_year,
        "genre_ids": [18],
        "genres": genres,
        "vote_average": vote_average,
        "vote_count": vote_count,
        "popularity": popularity,
        "rating_scale": rating_scale,
    }


def wikidata_record(tmdb_id: int) -> dict:
    return {
        "tmdb_source_movie_id": str(tmdb_id),
        "match_status": "EXACT_IDENTIFIER_MATCH",
        "wikidata_qid": f"Q{tmdb_id}",
        "english_label": f"Movie {tmdb_id}",
        "titles": [{"language": "en", "value": f"Movie {tmdb_id}", "normalized": f"movie {tmdb_id}"}],
        "alternate_titles": [],
        "imdb_id": f"tt{tmdb_id:07d}",
        "original_languages": ["Marathi"],
        "countries_of_origin": ["India"],
        "directors": ["Director A"],
        "publication_date": "2016-01-01T00:00:00Z",
    }


def validated_record(
    tmdb_id: int,
    *,
    language: str,
    classification: str = "VALIDATED_EXACT_MATCH",
    complete_identity_evidence: bool = True,
    warnings: list[str] | None = None,
) -> dict:
    return {
        "tmdb_movie_id": str(tmdb_id),
        "language": language,
        "validation_classification": classification,
        "complete_identity_evidence": complete_identity_evidence,
        "warnings": warnings or [],
    }


def write_run_dir(
    tmp_path: Path,
    *,
    run_id: str = "20260719T160000Z",
    movies: list[dict],
    validated_matches: list[dict],
    validation_recommendation: str = "GO_FOR_COHORT_BASELINES",
) -> Path:
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    wikidata_matches = [wikidata_record(int(movie["source_record_id"])) for movie in movies]
    requested_languages = sorted({str(movie["requested_language"]) for movie in movies})
    coverage_summary = {
        "per_language": {language: {"collected_tmdb_movie_count": sum(1 for movie in movies if movie["requested_language"] == language)} for language in requested_languages},
        "total": {"collected_tmdb_movie_count": len(movies)},
    }
    validation_summary = {
        "validator_version": "regional-evidence-validation-v1",
        "final_recommendation": validation_recommendation,
    }

    files = {
        "movies.jsonl": "\n".join(json.dumps(row, sort_keys=True) for row in movies) + "\n",
        "wikidata_matches.jsonl": "\n".join(json.dumps(row, sort_keys=True) for row in wikidata_matches) + "\n",
        "coverage_summary.json": json.dumps(coverage_summary, indent=2, sort_keys=True),
    }
    for name, content in files.items():
        (run_dir / name).write_text(content, encoding="utf-8")
    output_hashes = {name: hashlib.sha256((run_dir / name).read_bytes()).hexdigest() for name in files}
    run_manifest = {
        "run_id": run_id,
        "script_version": "regional-evidence-v1",
        "requested_languages": requested_languages,
        "sources_used": ["tmdb", "wikidata"],
        "source_urls": {"tmdb": "https://developer.themoviedb.org/", "wikidata": "https://query.wikidata.org/sparql"},
        "output_hashes": output_hashes,
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(run_manifest, indent=2, sort_keys=True), encoding="utf-8")

    validation_dir = run_dir / "validation"
    validation_dir.mkdir()
    (validation_dir / "validated_matches.jsonl").write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in validated_matches) + "\n",
        encoding="utf-8",
    )
    (validation_dir / "validation_summary.json").write_text(
        json.dumps(validation_summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (validation_dir / "validation_manifest.json").write_text(
        json.dumps({"validator_version": "regional-evidence-validation-v1"}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return run_dir


def write_review_file(path: Path, rows: list[dict[str, str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["tmdb_movie_id", "reviewer_decision"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_era_assignment_and_cohort_keys_are_deterministic():
    config = CohortBaselineConfig()

    assert assign_release_era(1975, config=config) == "pre_1980"
    assert assign_release_era(1994, config=config) == "1980_1999"
    assert assign_release_era(2005, config=config) == "2000_2009"
    assert assign_release_era(2016, config=config) == "2010_2019"
    assert assign_release_era(2024, config=config) == "2020_present"
    assert assign_release_era(None, config=config) == UNKNOWN_YEAR

    assert build_cohort_key(level="level_1", language="mr", era="2010_2019", primary_genre="Drama") == "language=mr|era=2010_2019|genre=drama"
    assert build_cohort_key(level="level_2", language="mr", era="2010_2019", primary_genre="Drama") == "language=mr|era=2010_2019"
    assert build_cohort_key(level="level_3", language="mr", era="2010_2019", primary_genre="Drama") == "language=mr"


def test_builder_assigns_four_levels_and_retains_sparse_unknown_genre_cohorts(tmp_path):
    movies = [
        movie_record(1, language="mr", genres=["Drama", "Comedy"], title="A", normalized_title="a"),
        movie_record(2, language="mr", genres=None, release_year=None, title="B", normalized_title="b"),
        movie_record(3, language="ml", genres=["Thriller"], title="C", normalized_title="c"),
    ]
    validated = [
        validated_record(1, language="mr"),
        validated_record(2, language="mr", classification="EXACT_MATCH_WITH_WARNINGS", complete_identity_evidence=True),
        validated_record(3, language="ml", classification="NO_MATCH", complete_identity_evidence=False),
    ]
    run_dir = write_run_dir(tmp_path, movies=movies, validated_matches=validated, validation_recommendation="GO_FOR_COHORT_BASELINES")

    result = build_regional_cohort_baselines(run_dir=run_dir, output_dir=tmp_path / "out")
    assignments = result["movie_assignments"]
    by_id = {row["tmdb_movie_id"]: row for row in assignments}

    assert len(assignments) == 3
    assert by_id["1"]["primary_genre"] == "drama"
    assert by_id["2"]["primary_genre"] == UNKNOWN_GENRE
    assert by_id["2"]["era"] == UNKNOWN_YEAR
    assert by_id["1"]["level_1_cohort_key"] == "language=mr|era=2010_2019|genre=drama"
    assert by_id["1"]["level_2_cohort_key"] == "language=mr|era=2010_2019"
    assert by_id["1"]["level_3_cohort_key"] == "language=mr"
    assert by_id["1"]["global_cohort_key"] == "global=regional_sample"
    assert by_id["1"]["selected_eligible_cohort_key"] is None
    assert by_id["1"]["selected_eligible_cohort_level"] == "unavailable"
    assert by_id["1"]["fallback_reason"] == "no_eligible_cohort"

    sparse_level_1 = next(row for row in result["cohort_records"] if row["cohort_key"] == "language=mr|era=2010_2019|genre=drama")
    assert sparse_level_1["eligible_for_normalization"] is False
    assert sparse_level_1["fallback_to"] == "language=mr|era=2010_2019"
    assert sparse_level_1["fallback_reason"] == "sparse_cohort:1<10"


def test_signal_statistics_handle_percentiles_log1p_and_invalid_values(tmp_path):
    movies = [
        movie_record(1, language="mr", vote_average=5.0, vote_count=0, popularity=0.0, genres=["Drama"]),
        movie_record(2, language="mr", vote_average=7.0, vote_count=9, popularity=9.0, genres=["Drama"]),
        movie_record(3, language="mr", vote_average=9.0, vote_count=99, popularity=99.0, genres=["Drama"]),
        movie_record(4, language="mr", vote_average=True, vote_count=-1, popularity="bad", genres=["Drama"]),
        movie_record(5, language="mr", vote_average=8.0, vote_count=25, popularity=16.0, genres=["Drama"], rating_scale="stars-5"),
    ]
    validated = [validated_record(index, language="mr") for index in range(1, 6)]
    run_dir = write_run_dir(tmp_path, movies=movies, validated_matches=validated)

    result = build_regional_cohort_baselines(run_dir=run_dir, output_dir=tmp_path / "out")
    language_cohort = next(row for row in result["cohort_records"] if row["cohort_key"] == "language=mr")
    rating_stats = language_cohort["signal_statistics"]["tmdb_rating"]
    normalized_stats = language_cohort["signal_statistics"]["tmdb_rating_normalized"]
    vote_stats = language_cohort["signal_statistics"]["tmdb_vote_count"]
    vote_log_stats = language_cohort["signal_statistics"]["tmdb_vote_count_log1p"]
    popularity_stats = language_cohort["signal_statistics"]["tmdb_popularity"]

    assert rating_stats["count"] == 3
    assert rating_stats["missing_count"] == 2
    assert rating_stats["mean"] == 7.0
    assert rating_stats["median"] == 7.0
    assert rating_stats["p25"] == 6.0
    assert rating_stats["p75"] == 8.0
    assert rating_stats["population_stddev"] == 1.632993
    assert normalized_stats["maximum"] == 0.9
    assert vote_stats["maximum"] == 99.0
    assert vote_stats["zero_count"] == 1
    assert vote_log_stats["count"] == 4
    assert popularity_stats["count"] == 4
    assert language_cohort["signal_exclusion_reasons"]["tmdb_rating"]["boolean_not_allowed"] == 1
    assert language_cohort["signal_exclusion_reasons"]["tmdb_rating"]["unknown_rating_scale"] == 1
    assert language_cohort["signal_exclusion_reasons"]["tmdb_vote_count"]["negative_not_allowed"] == 1
    assert language_cohort["signal_exclusion_reasons"]["tmdb_popularity"]["malformed_number"] == 1


def test_review_decisions_control_wikidata_signal_eligibility_and_pending_activation(tmp_path):
    movies = [
        movie_record(1, language="mr", genres=["Drama"]),
        movie_record(2, language="mr", genres=["Drama"]),
        movie_record(3, language="mr", genres=["Drama"]),
    ]
    validated = [
        validated_record(1, language="mr", classification="AMBIGUOUS_REVIEW_REQUIRED", complete_identity_evidence=False),
        validated_record(2, language="mr", classification="EXACT_MATCH_WITH_WARNINGS", complete_identity_evidence=True),
        validated_record(3, language="mr", classification="VALIDATED_EXACT_MATCH", complete_identity_evidence=True),
    ]
    run_dir = write_run_dir(tmp_path, movies=movies, validated_matches=validated)

    pending = build_regional_cohort_baselines(run_dir=run_dir, output_dir=tmp_path / "pending")
    pending_by_id = {row["tmdb_movie_id"]: row for row in pending["movie_assignments"]}
    assert pending["activation_eligible"] is False
    assert pending["manual_review_status"] == "PENDING"
    assert pending["phase_recommendation"] == PHASE_EXPAND
    assert pending_by_id["1"]["signal_eligibility_flags"]["wikidata_identity"] is False
    assert pending_by_id["2"]["signal_eligibility_flags"]["wikidata_identity"] is True

    review_file = write_review_file(
        tmp_path / "review.csv",
        [
            {"tmdb_movie_id": "1", "reviewer_decision": "CONFIRMED"},
            {"tmdb_movie_id": "2", "reviewer_decision": "REJECTED"},
            {"tmdb_movie_id": "3", "reviewer_decision": "CONFIRMED"},
        ],
    )
    reviewed = build_regional_cohort_baselines(run_dir=run_dir, output_dir=tmp_path / "reviewed", review_file=review_file)
    reviewed_by_id = {row["tmdb_movie_id"]: row for row in reviewed["movie_assignments"]}

    assert reviewed_by_id["1"]["signal_eligibility_flags"]["wikidata_identity"] is False
    assert reviewed_by_id["2"]["signal_eligibility_flags"]["wikidata_identity"] is False
    assert reviewed_by_id["3"]["signal_eligibility_flags"]["wikidata_identity"] is True


def test_readiness_and_phase_recommendation_cover_ready_expand_and_blocked(tmp_path):
    ready_movies = []
    ready_validated = []
    movie_id = 1
    for language in ("mr", "ml", "ta"):
        for index in range(30):
            ready_movies.append(
                movie_record(
                    movie_id,
                    language=language,
                    release_year=2016 + (index % 3),
                    genres=["Drama"],
                    vote_average=7.0 + (index % 2),
                    vote_count=100 + index,
                    popularity=20.0 + index,
                )
            )
            ready_validated.append(validated_record(movie_id, language=language))
            movie_id += 1
    ready_run = write_run_dir(tmp_path, run_id="20260719T160001Z", movies=ready_movies, validated_matches=ready_validated)
    ready_review = write_review_file(
        tmp_path / "ready-review.csv",
        [{"tmdb_movie_id": str(index), "reviewer_decision": "CONFIRMED"} for index in range(1, movie_id)],
    )
    ready_result = build_regional_cohort_baselines(run_dir=ready_run, output_dir=tmp_path / "ready-out", review_file=ready_review)

    assert ready_result["phase_recommendation"] == PHASE_PROCEED
    assert all(
        row["readiness"] == READINESS_READY
        for row in ready_result["coverage_report"]["per_language_readiness"].values()
    )

    expand_movies = [movie_record(index, language="mr", genres=["Drama"]) for index in range(1, 12)]
    expand_validated = [validated_record(index, language="mr") for index in range(1, 12)]
    expand_run = write_run_dir(tmp_path, run_id="20260719T160002Z", movies=expand_movies, validated_matches=expand_validated)
    expand_result = build_regional_cohort_baselines(run_dir=expand_run, output_dir=tmp_path / "expand-out")
    assert expand_result["phase_recommendation"] == PHASE_EXPAND
    assert expand_result["coverage_report"]["per_language_readiness"]["mr"]["readiness"] == READINESS_INSUFFICIENT

    blocked_run = write_run_dir(
        tmp_path,
        run_id="20260719T160003Z",
        movies=ready_movies,
        validated_matches=ready_validated,
        validation_recommendation="BLOCKED_BY_ENTITY_RESOLUTION_QUALITY",
    )
    blocked_result = build_regional_cohort_baselines(run_dir=blocked_run, output_dir=tmp_path / "blocked-out", review_file=ready_review)
    assert blocked_result["phase_recommendation"] == PHASE_BLOCKED
    assert all(
        row["readiness"] == READINESS_ENTITY_BLOCKED
        for row in blocked_result["coverage_report"]["per_language_readiness"].values()
    )


def test_outputs_are_deterministic_and_support_one_hundred_fifty_movies(tmp_path):
    movies = []
    validated = []
    movie_id = 1
    for language in ("mr", "ml", "ta"):
        for index in range(50):
            movies.append(
                movie_record(
                    movie_id,
                    language=language,
                    title=f"{language}-{index}",
                    normalized_title=f"{language}-{index}",
                    release_year=2010 + (index % 10),
                    genres=["Drama"] if index % 2 == 0 else ["Comedy"],
                    vote_average=6.0 + (index % 4),
                    vote_count=50 + index,
                    popularity=5.0 + index,
                )
            )
            validated.append(validated_record(movie_id, language=language))
            movie_id += 1
    run_dir = write_run_dir(tmp_path, run_id="20260719T160004Z", movies=movies, validated_matches=validated)
    review_file = write_review_file(
        tmp_path / "bulk-review.csv",
        [{"tmdb_movie_id": str(index), "reviewer_decision": "CONFIRMED"} for index in range(1, movie_id)],
    )

    first = build_regional_cohort_baselines(run_dir=run_dir, output_dir=tmp_path / "first", review_file=review_file)
    second = build_regional_cohort_baselines(run_dir=run_dir, output_dir=tmp_path / "second", review_file=review_file)

    assert len(first["movie_assignments"]) == 150
    assert len(second["movie_assignments"]) == 150
    for filename in ("cohort_baselines.json", "movie_cohort_assignments.jsonl", "cohort_coverage_report.json"):
        assert hashlib.sha256((first["output_dir"] / filename).read_bytes()).hexdigest() == hashlib.sha256(
            (second["output_dir"] / filename).read_bytes()
        ).hexdigest()
    assert (run_dir / "movies.jsonl").exists()
    assert (run_dir / "wikidata_matches.jsonl").exists()
