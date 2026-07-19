import hashlib
import json
from pathlib import Path

from app.regional_cohort_baselines import build_regional_cohort_baselines
from app.regional_shadow_scoring import (
    BLOCKED_BY_LOW_COVERAGE,
    BLOCKED_FROM_DATA_APPROVAL,
    PROVISIONAL_SHADOW_ONLY,
    REVIEW_INPUT_REQUIRED,
    run_regional_shadow_scoring,
)


def movie_record(
    tmdb_id: int,
    *,
    language: str,
    release_year: int,
    vote_average: float,
    vote_count: int,
    popularity: float,
    provider_position: int,
) -> dict:
    title = f"{language}-{tmdb_id}"
    return {
        "source_name": "tmdb",
        "source_record_id": str(tmdb_id),
        "title": title,
        "original_title": title,
        "normalized_title": title.casefold(),
        "requested_language": language,
        "original_language": language,
        "release_year": release_year,
        "genre_ids": [18],
        "vote_average": vote_average,
        "vote_count": vote_count,
        "popularity": popularity,
        "provider_position": provider_position,
    }


def validated_record(tmdb_id: int, *, language: str, classification: str = "VALIDATED_EXACT_MATCH", complete_identity_evidence: bool = True) -> dict:
    return {
        "tmdb_movie_id": str(tmdb_id),
        "language": language,
        "validation_classification": classification,
        "complete_identity_evidence": complete_identity_evidence,
        "warnings": [],
    }


def write_run_dir(
    tmp_path: Path,
    *,
    run_id: str,
    validation_recommendation: str,
    movies: list[dict],
    validated: list[dict],
) -> Path:
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "movies.jsonl").write_text("\n".join(json.dumps(row, sort_keys=True) for row in movies) + "\n", encoding="utf-8")
    wikidata_matches = [
        {
            "tmdb_source_movie_id": row["source_record_id"],
            "match_status": "EXACT_IDENTIFIER_MATCH",
            "wikidata_qid": f"Q{row['source_record_id']}",
            "english_label": row["title"],
            "titles": [],
            "alternate_titles": [],
            "imdb_id": f"tt{int(row['source_record_id']):07d}",
            "original_languages": ["Marathi"],
            "countries_of_origin": ["India"],
            "directors": ["Director A"],
            "publication_date": f"{row['release_year']}-01-01T00:00:00Z",
        }
        for row in movies
    ]
    (run_dir / "wikidata_matches.jsonl").write_text("\n".join(json.dumps(row, sort_keys=True) for row in wikidata_matches) + "\n", encoding="utf-8")
    (run_dir / "coverage_summary.json").write_text(json.dumps({"total": {"collected_tmdb_movie_count": len(movies)}}, indent=2, sort_keys=True), encoding="utf-8")
    hashes = {
        name: hashlib.sha256((run_dir / name).read_bytes()).hexdigest()
        for name in ("movies.jsonl", "wikidata_matches.jsonl", "coverage_summary.json")
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"run_id": run_id, "output_hashes": hashes, "script_version": "regional-evidence-v1", "sources_used": ["tmdb", "wikidata"], "source_urls": {}}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    validation_dir = run_dir / "validation"
    validation_dir.mkdir()
    (validation_dir / "validated_matches.jsonl").write_text("\n".join(json.dumps(row, sort_keys=True) for row in validated) + "\n", encoding="utf-8")
    (validation_dir / "validation_summary.json").write_text(
        json.dumps({"validator_version": "regional-evidence-validation-v1", "final_recommendation": validation_recommendation}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (validation_dir / "validation_manifest.json").write_text(json.dumps({"validator_version": "regional-evidence-validation-v1"}, indent=2, sort_keys=True), encoding="utf-8")
    return run_dir


def build_baseline(tmp_path: Path, *, run_dir: Path) -> Path:
    output_dir = tmp_path / f"{run_dir.name}-baseline"
    build_regional_cohort_baselines(run_dir=run_dir, output_dir=output_dir)
    return output_dir


def make_movies() -> tuple[list[dict], list[dict]]:
    movies = []
    validated = []
    tmdb_id = 1
    for language, offset in (("mr", 0), ("ml", 100), ("ta", 200)):
        for index in range(12):
            movies.append(
                movie_record(
                    tmdb_id=tmdb_id,
                    language=language,
                    release_year=2010 + (index % 3),
                    vote_average=6.0 + (index % 4),
                    vote_count=10 + index + offset,
                    popularity=5.0 + index,
                    provider_position=index,
                )
            )
            validated.append(validated_record(tmdb_id, language=language))
            tmdb_id += 1
    return movies, validated


def test_shadow_runner_builds_outputs_and_comparison_metrics(tmp_path):
    movies, validated = make_movies()
    run_dir = write_run_dir(
        tmp_path,
        run_id="20260719T170000Z",
        validation_recommendation=REVIEW_INPUT_REQUIRED,
        movies=movies,
        validated=validated,
    )
    baseline_dir = build_baseline(tmp_path, run_dir=run_dir)

    result = run_regional_shadow_scoring(run_dir=run_dir, baseline_dir=baseline_dir, output_dir=tmp_path / "shadow")

    assert result["gate_status"] == REVIEW_INPUT_REQUIRED
    assert result["provisional_status"] == PROVISIONAL_SHADOW_ONLY
    assert len(result["shadow_rows"]) == len(movies)
    assert result["summary"]["movies_processed"] == len(movies)
    assert result["summary"]["v2_scorable_count"] == len(movies)
    assert result["summary"]["v1_v2_metrics"]["spearman_rank_correlation"] is not None
    assert (tmp_path / "shadow" / "shadow_scores.jsonl").exists()
    assert (tmp_path / "shadow" / "shadow_ranking.json").exists()
    assert (tmp_path / "shadow" / "v1_v2_comparison.json").exists()
    assert (tmp_path / "shadow" / "shadow_summary.json").exists()
    assert (tmp_path / "shadow" / "shadow_manifest.json").exists()


def test_blocked_gate_maps_to_blocked_from_data_approval(tmp_path):
    movies, validated = make_movies()
    run_dir = write_run_dir(
        tmp_path,
        run_id="20260719T170001Z",
        validation_recommendation=BLOCKED_BY_LOW_COVERAGE,
        movies=movies,
        validated=validated,
    )
    baseline_dir = build_baseline(tmp_path, run_dir=run_dir)

    result = run_regional_shadow_scoring(run_dir=run_dir, baseline_dir=baseline_dir, output_dir=tmp_path / "shadow")

    assert result["gate_status"] == BLOCKED_BY_LOW_COVERAGE
    assert result["provisional_status"] == BLOCKED_FROM_DATA_APPROVAL
    assert result["summary"]["recommendation"] == BLOCKED_FROM_DATA_APPROVAL


def test_assignment_mismatch_fails_safely_per_movie(tmp_path):
    movies, validated = make_movies()
    run_dir = write_run_dir(
        tmp_path,
        run_id="20260719T170002Z",
        validation_recommendation=REVIEW_INPUT_REQUIRED,
        movies=movies,
        validated=validated,
    )
    baseline_dir = build_baseline(tmp_path, run_dir=run_dir)
    assignments_path = baseline_dir / "movie_cohort_assignments.jsonl"
    rows = [json.loads(line) for line in assignments_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows[0]["selected_eligible_cohort_key"] = "language=missing"
    assignments_path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")

    result = run_regional_shadow_scoring(run_dir=run_dir, baseline_dir=baseline_dir, output_dir=tmp_path / "shadow")

    first = next(row for row in result["shadow_rows"] if row["tmdb_movie_id"] == rows[0]["tmdb_movie_id"])
    assert first["raw_total"] is None
    assert "baseline_assignment_mismatch" in first["warnings"]


def test_shadow_outputs_are_deterministic_except_manifest_timestamp(tmp_path):
    movies, validated = make_movies()
    run_dir = write_run_dir(
        tmp_path,
        run_id="20260719T170003Z",
        validation_recommendation=REVIEW_INPUT_REQUIRED,
        movies=movies,
        validated=validated,
    )
    baseline_dir = build_baseline(tmp_path, run_dir=run_dir)
    first_dir = tmp_path / "shadow-a"
    second_dir = tmp_path / "shadow-b"

    run_regional_shadow_scoring(run_dir=run_dir, baseline_dir=baseline_dir, output_dir=first_dir)
    run_regional_shadow_scoring(run_dir=run_dir, baseline_dir=baseline_dir, output_dir=second_dir)

    for name in ("shadow_scores.jsonl", "shadow_ranking.json", "v1_v2_comparison.json", "shadow_summary.json"):
        assert hashlib.sha256((first_dir / name).read_bytes()).hexdigest() == hashlib.sha256((second_dir / name).read_bytes()).hexdigest()


def test_shadow_runner_allows_missing_validation_summary_and_stays_provisional(tmp_path):
    movies, validated = make_movies()
    run_dir = write_run_dir(
        tmp_path,
        run_id="20260719T170004Z",
        validation_recommendation=REVIEW_INPUT_REQUIRED,
        movies=movies,
        validated=validated,
    )
    (run_dir / "validation" / "validation_summary.json").unlink()
    baseline_dir = build_baseline(tmp_path, run_dir=run_dir)

    result = run_regional_shadow_scoring(run_dir=run_dir, baseline_dir=baseline_dir, output_dir=tmp_path / "shadow")

    assert result["gate_status"] == REVIEW_INPUT_REQUIRED
    assert result["provisional_status"] == PROVISIONAL_SHADOW_ONLY


def test_unavailable_selected_cohort_is_reported_without_assignment_mismatch(tmp_path):
    movies = [
        movie_record(tmdb_id=1, language="ta", release_year=2020, vote_average=7.0, vote_count=10, popularity=5.0, provider_position=0),
        movie_record(tmdb_id=2, language="ta", release_year=2021, vote_average=8.0, vote_count=11, popularity=6.0, provider_position=1),
    ]
    validated = [
        validated_record(1, language="ta"),
        validated_record(2, language="ta"),
    ]
    run_dir = write_run_dir(
        tmp_path,
        run_id="20260719T170005Z",
        validation_recommendation=REVIEW_INPUT_REQUIRED,
        movies=movies,
        validated=validated,
    )
    baseline_dir = build_baseline(tmp_path, run_dir=run_dir)

    result = run_regional_shadow_scoring(run_dir=run_dir, baseline_dir=baseline_dir, output_dir=tmp_path / "shadow")

    assert result["summary"]["v2_scorable_count"] == 0
    for row in result["shadow_rows"]:
        assert "unavailable_selected_cohort" in row["warnings"]
        assert "baseline_assignment_mismatch" not in row["warnings"]
