import csv
import hashlib
import json
from pathlib import Path

from app.regional_cohort_baselines import CohortBaselineConfig, build_regional_cohort_baselines
from app.regional_shadow_evaluation import (
    EVALUATION_MODE_DIAGNOSTIC_ONLY,
    EVALUATION_MODE_HUMAN_JUDGMENT,
    PHASE_BLOCKED_REGRESSION,
    PHASE_DIAGNOSTIC_ONLY,
    PHASE_READY_ALL,
    evaluate_regional_shadow_ranking,
)
from app.regional_shadow_scoring import REVIEW_INPUT_REQUIRED, run_regional_shadow_scoring


def movie_record(
    tmdb_id: int,
    *,
    language: str,
    title: str,
    vote_average: float | None,
    vote_count: int | None,
    popularity: float | None,
    provider_position: int,
) -> dict:
    return {
        "source_name": "tmdb",
        "source_record_id": str(tmdb_id),
        "title": title,
        "original_title": title,
        "normalized_title": title.casefold(),
        "requested_language": language,
        "original_language": language,
        "release_year": 2020,
        "normalized_genres": ["drama"],
        "vote_average": vote_average,
        "vote_count": vote_count,
        "popularity": popularity,
        "provider_position": provider_position,
    }


def validated_record(
    tmdb_id: int,
    *,
    language: str,
    classification: str = "VALIDATED_EXACT_MATCH",
    complete_identity_evidence: bool = True,
) -> dict:
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
    movies: list[dict],
    validated: list[dict],
) -> Path:
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "movies.jsonl").write_text("\n".join(json.dumps(row, sort_keys=True) for row in movies) + "\n", encoding="utf-8")
    wikidata_matches = []
    for row in movies:
        wikidata_matches.append(
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
                "publication_date": "2020-01-01T00:00:00Z",
            }
        )
    (run_dir / "wikidata_matches.jsonl").write_text("\n".join(json.dumps(row, sort_keys=True) for row in wikidata_matches) + "\n", encoding="utf-8")
    (run_dir / "coverage_summary.json").write_text(json.dumps({"total": {"collected_tmdb_movie_count": len(movies)}}, indent=2, sort_keys=True), encoding="utf-8")
    hashes = {
        name: hashlib.sha256((run_dir / name).read_bytes()).hexdigest()
        for name in ("movies.jsonl", "wikidata_matches.jsonl", "coverage_summary.json")
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "output_hashes": hashes,
                "script_version": "regional-evidence-v1",
                "sources_used": ["tmdb", "wikidata"],
                "source_urls": {},
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    validation_dir = run_dir / "validation"
    validation_dir.mkdir()
    (validation_dir / "validated_matches.jsonl").write_text("\n".join(json.dumps(row, sort_keys=True) for row in validated) + "\n", encoding="utf-8")
    (validation_dir / "validation_summary.json").write_text(
        json.dumps({"validator_version": "regional-evidence-validation-v1", "final_recommendation": REVIEW_INPUT_REQUIRED}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (validation_dir / "validation_manifest.json").write_text(json.dumps({"validator_version": "regional-evidence-validation-v1"}, indent=2, sort_keys=True), encoding="utf-8")
    return run_dir


def build_review_file(tmp_path: Path) -> Path:
    review_file = tmp_path / "review.csv"
    with review_file.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("tmdb_movie_id", "reviewer_decision"))
        writer.writeheader()
        writer.writerow({"tmdb_movie_id": "2", "reviewer_decision": "REJECTED"})
    return review_file


def make_movies() -> tuple[list[dict], list[dict]]:
    movies = [
        movie_record(1, language="mr", title="mr-acclaimed-low-reach", vote_average=8.8, vote_count=5, popularity=1.0, provider_position=0),
        movie_record(2, language="mr", title="mr-popular-mainstream", vote_average=5.5, vote_count=500, popularity=85.0, provider_position=1),
        movie_record(3, language="mr", title="mr-older-sparse", vote_average=7.2, vote_count=10, popularity=2.0, provider_position=2),
        movie_record(4, language="mr", title="mr-low-rating-high-pop", vote_average=4.9, vote_count=450, popularity=88.0, provider_position=3),
        movie_record(5, language="ml", title="ml-acclaimed-medium", vote_average=8.5, vote_count=40, popularity=12.0, provider_position=0),
        movie_record(6, language="ml", title="ml-commercial-hit", vote_average=6.0, vote_count=900, popularity=90.0, provider_position=1),
        movie_record(7, language="ml", title="ml-recent-high-rating", vote_average=8.9, vote_count=15, popularity=6.0, provider_position=2),
        movie_record(8, language="ml", title="ml-weak-high-reach", vote_average=4.7, vote_count=850, popularity=75.0, provider_position=3),
        movie_record(9, language="ta", title="ta-older-classic", vote_average=8.7, vote_count=12, popularity=4.0, provider_position=0),
        movie_record(10, language="ta", title="ta-recent-blockbuster", vote_average=6.4, vote_count=1000, popularity=98.0, provider_position=1),
        movie_record(11, language="ta", title="ta-high-rating-low-vote", vote_average=None, vote_count=8, popularity=3.0, provider_position=2),
        movie_record(12, language="ta", title="ta-medium-rating-high-pop", vote_average=6.5, vote_count=None, popularity=None, provider_position=3),
    ]
    validated = [
        validated_record(1, language="mr"),
        validated_record(2, language="mr", classification="EXACT_MATCH_WITH_WARNINGS"),
        validated_record(3, language="mr"),
        validated_record(4, language="mr"),
        validated_record(5, language="ml"),
        validated_record(6, language="ml"),
        validated_record(7, language="ml"),
        validated_record(8, language="ml", classification="SOURCE_ERROR", complete_identity_evidence=False),
        validated_record(9, language="ta"),
        validated_record(10, language="ta"),
        validated_record(11, language="ta"),
        validated_record(12, language="ta"),
    ]
    return movies, validated


def build_shadow_fixture(tmp_path: Path) -> tuple[Path, Path]:
    movies, validated = make_movies()
    run_dir = write_run_dir(tmp_path, run_id="20260719T180000Z", movies=movies, validated=validated)
    review_file = build_review_file(tmp_path)
    baseline_dir = tmp_path / "baseline"
    build_regional_cohort_baselines(
        run_dir=run_dir,
        output_dir=baseline_dir,
        review_file=review_file,
        config=CohortBaselineConfig(level_thresholds={"level_1": 2, "level_2": 2, "level_3": 3, "level_4": 5}),
    )
    shadow_dir = tmp_path / "shadow"
    run_regional_shadow_scoring(run_dir=run_dir, baseline_dir=baseline_dir, output_dir=shadow_dir)
    return run_dir, shadow_dir


def test_evaluation_builds_diagnostic_outputs_and_metrics(tmp_path):
    _run_dir, shadow_dir = build_shadow_fixture(tmp_path)

    result = evaluate_regional_shadow_ranking(shadow_dir=shadow_dir, output_dir=tmp_path / "evaluation")

    summary = result["summary"]
    assert summary["evaluation_mode"] == EVALUATION_MODE_DIAGNOSTIC_ONLY
    assert summary["phase_recommendation"] in {PHASE_DIAGNOSTIC_ONLY, PHASE_READY_ALL}
    assert summary["movie_counts"]["evaluated"] == 12
    assert summary["diagnostic_metrics"]["spearman_rank_correlation"] is not None
    assert summary["diagnostic_metrics"]["kendall_tau_b"] is not None
    assert summary["diagnostic_metrics"]["top_5_overlap"]["count"] >= 0
    assert summary["diagnostic_metrics"]["quality_reach_movement"]["high_rating_low_reach_up"]["count"] >= 0
    assert "mr" in summary["language_metrics"]
    assert "level_1" in summary["fallback_metrics"]
    assert "high" in summary["confidence_metrics"]
    assert summary["missing_data_metrics"]["missing_quality_count"] == 1
    assert summary["human_judgment_metrics"]["status"] == "NOT_SUPPLIED_DIAGNOSTIC_ONLY"
    assert (tmp_path / "evaluation" / "evaluation_summary.json").exists()
    assert (tmp_path / "evaluation" / "evaluation_cases.jsonl").exists()
    assert (tmp_path / "evaluation" / "evaluation_regressions.json").exists()
    assert (tmp_path / "evaluation" / "language_comparison.json").exists()
    assert (tmp_path / "evaluation" / "evaluation_manifest.json").exists()


def test_evaluation_is_deterministic_except_manifest_timestamp(tmp_path):
    _run_dir, shadow_dir = build_shadow_fixture(tmp_path)
    first_dir = tmp_path / "evaluation-a"
    second_dir = tmp_path / "evaluation-b"

    evaluate_regional_shadow_ranking(shadow_dir=shadow_dir, output_dir=first_dir)
    evaluate_regional_shadow_ranking(shadow_dir=shadow_dir, output_dir=second_dir)

    for name in (
        "evaluation_summary.json",
        "evaluation_cases.jsonl",
        "evaluation_regressions.json",
        "language_comparison.json",
    ):
        assert hashlib.sha256((first_dir / name).read_bytes()).hexdigest() == hashlib.sha256((second_dir / name).read_bytes()).hexdigest()


def test_invalid_shadow_score_range_blocks_evaluation(tmp_path):
    _run_dir, shadow_dir = build_shadow_fixture(tmp_path)
    rows = [json.loads(line) for line in (shadow_dir / "shadow_scores.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    rows[0]["raw_total"] = 1.2
    rows[0]["display_total"] = 120.0
    (shadow_dir / "shadow_scores.jsonl").write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")

    result = evaluate_regional_shadow_ranking(shadow_dir=shadow_dir, output_dir=tmp_path / "evaluation")

    assert result["summary"]["phase_recommendation"] == PHASE_BLOCKED_REGRESSION
    assert result["summary"]["regression_counts"]["blocking"] >= 1


def test_duplicate_movie_detection_is_blocking(tmp_path):
    _run_dir, shadow_dir = build_shadow_fixture(tmp_path)
    lines = [line for line in (shadow_dir / "shadow_scores.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    lines.append(lines[0])
    (shadow_dir / "shadow_scores.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = evaluate_regional_shadow_ranking(shadow_dir=shadow_dir, output_dir=tmp_path / "evaluation")

    assert result["summary"]["phase_recommendation"] == PHASE_BLOCKED_REGRESSION
    assert any(item["code"] == "DUPLICATE_MOVIE_IDS" for item in result["regressions"]["blocking_regressions"])


def test_human_judgment_mode_computes_metrics(tmp_path):
    _run_dir, shadow_dir = build_shadow_fixture(tmp_path)
    judgment_file = tmp_path / "judgments.csv"
    with judgment_file.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "evaluation_case_id",
                "query_or_context",
                "tmdb_movie_id",
                "language",
                "relevance_grade",
                "quality_grade",
                "confidence_in_judgment",
                "reviewer_notes",
            ),
        )
        writer.writeheader()
        writer.writerow({"evaluation_case_id": "1", "query_or_context": "mr", "tmdb_movie_id": "1", "language": "mr", "relevance_grade": "3", "quality_grade": "3", "confidence_in_judgment": "HIGH", "reviewer_notes": "best"})
        writer.writerow({"evaluation_case_id": "2", "query_or_context": "mr", "tmdb_movie_id": "2", "language": "mr", "relevance_grade": "1", "quality_grade": "1", "confidence_in_judgment": "MEDIUM", "reviewer_notes": "commercial"})
        writer.writerow({"evaluation_case_id": "5", "query_or_context": "ml", "tmdb_movie_id": "5", "language": "ml", "relevance_grade": "2", "quality_grade": "2", "confidence_in_judgment": "HIGH", "reviewer_notes": "strong"})

    result = evaluate_regional_shadow_ranking(
        shadow_dir=shadow_dir,
        output_dir=tmp_path / "evaluation",
        judgment_file=judgment_file,
    )

    human = result["summary"]["human_judgment_metrics"]
    assert result["summary"]["evaluation_mode"] == EVALUATION_MODE_HUMAN_JUDGMENT
    assert human["status"] == "HUMAN_JUDGMENT_FILE_USED"
    assert human["overall"]["v1"]["ndcg_at_5"] is not None
    assert human["overall"]["v2"]["precision_at_5"] is not None
    assert "mr" in human["per_language"]


def test_invalid_judgment_grade_is_rejected(tmp_path):
    _run_dir, shadow_dir = build_shadow_fixture(tmp_path)
    judgment_file = tmp_path / "judgments.csv"
    with judgment_file.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "evaluation_case_id",
                "query_or_context",
                "tmdb_movie_id",
                "language",
                "relevance_grade",
                "quality_grade",
                "confidence_in_judgment",
                "reviewer_notes",
            ),
        )
        writer.writeheader()
        writer.writerow({"evaluation_case_id": "1", "query_or_context": "mr", "tmdb_movie_id": "1", "language": "mr", "relevance_grade": "9", "quality_grade": "1", "confidence_in_judgment": "HIGH", "reviewer_notes": "bad"})

    try:
        evaluate_regional_shadow_ranking(shadow_dir=shadow_dir, output_dir=tmp_path / "evaluation", judgment_file=judgment_file)
    except ValueError as exc:
        assert str(exc) == "invalid relevance_grade: 9"
    else:
        raise AssertionError("expected ValueError")


def test_duplicate_judgment_row_is_rejected(tmp_path):
    _run_dir, shadow_dir = build_shadow_fixture(tmp_path)
    judgment_file = tmp_path / "judgments.csv"
    with judgment_file.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "evaluation_case_id",
                "query_or_context",
                "tmdb_movie_id",
                "language",
                "relevance_grade",
                "quality_grade",
                "confidence_in_judgment",
                "reviewer_notes",
            ),
        )
        writer.writeheader()
        row = {"evaluation_case_id": "1", "query_or_context": "mr", "tmdb_movie_id": "1", "language": "mr", "relevance_grade": "3", "quality_grade": "3", "confidence_in_judgment": "HIGH", "reviewer_notes": "dup"}
        writer.writerow(row)
        writer.writerow(row)

    try:
        evaluate_regional_shadow_ranking(shadow_dir=shadow_dir, output_dir=tmp_path / "evaluation", judgment_file=judgment_file)
    except ValueError as exc:
        assert str(exc) == "duplicate judgment row for evaluation_case_id=1 tmdb_movie_id=1"
    else:
        raise AssertionError("expected ValueError")
