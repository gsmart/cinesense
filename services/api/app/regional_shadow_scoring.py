from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from app.cine_score_v2 import (
    SCORE_VERSION,
    CohortSignalSamples,
    ShadowScoreWeights,
    compute_cine_score_v2_shadow,
    load_baseline_hash,
)
from app.core.scoring import compute_cine_score_v1
from app.regional_cohort_baselines import BASELINE_SCHEMA_VERSION, READINESS_READY

DEFAULT_OUTPUT_ROOT = Path("/tmp/cinesense-regional-shadow")
GO_FOR_ALL_LANGUAGES = "GO_FOR_ALL_LANGUAGES"
GO_FOR_LIMITED_LANGUAGES = "GO_FOR_LIMITED_LANGUAGES"
REVIEW_INPUT_REQUIRED = "REVIEW_INPUT_REQUIRED"
REVIEW_INPUT_INCOMPLETE = "REVIEW_INPUT_INCOMPLETE"
BLOCKED_BY_ENTITY_RESOLUTION_QUALITY = "BLOCKED_BY_ENTITY_RESOLUTION_QUALITY"
BLOCKED_BY_LOW_COVERAGE = "BLOCKED_BY_LOW_COVERAGE"
APPROVED_FOR_SHADOW = "APPROVED_FOR_SHADOW"
PROVISIONAL_SHADOW_ONLY = "PROVISIONAL_SHADOW_ONLY"
BLOCKED_FROM_DATA_APPROVAL = "BLOCKED_FROM_DATA_APPROVAL"


def run_regional_shadow_scoring(
    *,
    run_dir: Path,
    baseline_dir: Path,
    output_dir: Path | None = None,
    languages: list[str] | None = None,
    weights: ShadowScoreWeights | None = None,
) -> dict[str, Any]:
    weights = weights or ShadowScoreWeights()
    weights.validate()
    context = _load_shadow_context(
        run_dir=Path(run_dir).resolve(),
        baseline_dir=Path(baseline_dir).resolve(),
        requested_languages=languages or [],
    )
    output_dir = (Path(output_dir).resolve() if output_dir else (DEFAULT_OUTPUT_ROOT / context["run_id"]).resolve())
    output_dir.mkdir(parents=True, exist_ok=True)

    shadow_rows = []
    for assignment in context["assignments"]:
        row_warnings = []
        language = assignment["original_language"]
        if context["requested_languages"] and language not in context["requested_languages"]:
            continue
        if language not in context["allowed_languages"]:
            row = _blocked_language_row(
                assignment=assignment,
                baseline_hash=context["baseline_hash"],
                gate_status=context["gate_status"],
                activation_eligible=context["activation_eligible"],
            )
            shadow_rows.append(row)
            continue

        selected_key = assignment.get("selected_eligible_cohort_key")
        selected_level = assignment.get("selected_eligible_cohort_level")
        if selected_level == "unavailable" or selected_key is None:
            shadow_rows.append(
                compute_cine_score_v2_shadow(
                    assignment=assignment,
                    cohort_record=None,
                    cohort_samples=None,
                    baseline_hash=context["baseline_hash"],
                    provisional_status=context["provisional_status"],
                    activation_eligible=context["activation_eligible"],
                    warnings=["unavailable_selected_cohort"],
                    weights=weights,
                )
            )
            continue
        cohort_record = context["cohort_by_key"].get(selected_key) if selected_key else None
        if cohort_record is None or cohort_record.get("cohort_level") != selected_level:
            row_warnings.append("baseline_assignment_mismatch")
            shadow_rows.append(
                compute_cine_score_v2_shadow(
                    assignment=assignment,
                    cohort_record=None,
                    cohort_samples=None,
                    baseline_hash=context["baseline_hash"],
                    provisional_status=context["provisional_status"],
                    activation_eligible=context["activation_eligible"],
                    warnings=row_warnings,
                    weights=weights,
                )
            )
            continue
        cohort_samples = context["cohort_samples"].get(selected_key)
        if cohort_samples is None:
            row_warnings.append("missing_cohort_samples")
        shadow_rows.append(
            compute_cine_score_v2_shadow(
                assignment=assignment,
                cohort_record=cohort_record,
                cohort_samples=cohort_samples,
                baseline_hash=context["baseline_hash"],
                provisional_status=context["provisional_status"],
                activation_eligible=context["activation_eligible"],
                warnings=row_warnings,
                weights=weights,
            )
        )

    v1_proxy_rows = [_compute_v1_proxy(movie=context["movies_by_id"][row["tmdb_movie_id"]]) for row in shadow_rows]
    comparison_rows = _build_comparisons(
        shadow_rows=shadow_rows,
        v1_proxy_rows=v1_proxy_rows,
        assignments_by_id=context["assignments_by_id"],
        movies_by_id=context["movies_by_id"],
    )
    ranking_output = _build_shadow_ranking(
        shadow_rows=shadow_rows,
        assignments_by_id=context["assignments_by_id"],
        movies_by_id=context["movies_by_id"],
    )
    summary = _build_summary(
        shadow_rows=shadow_rows,
        comparison_rows=comparison_rows,
        assignments_by_id=context["assignments_by_id"],
        gate_status=context["gate_status"],
        provisional_status=context["provisional_status"],
        activation_eligible=context["activation_eligible"],
        allowed_languages=context["allowed_languages"],
    )

    scores_path = output_dir / "shadow_scores.jsonl"
    ranking_path = output_dir / "shadow_ranking.json"
    comparison_path = output_dir / "v1_v2_comparison.json"
    summary_path = output_dir / "shadow_summary.json"
    manifest_path = output_dir / "shadow_manifest.json"

    _write_jsonl(scores_path, shadow_rows)
    ranking_path.write_text(json.dumps(ranking_output, indent=2, sort_keys=True), encoding="utf-8")
    comparison_path.write_text(json.dumps({"rows": comparison_rows}, indent=2, sort_keys=True), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    manifest = {
        "schema_version": "regional-shadow-scoring-v1",
        "score_version": SCORE_VERSION,
        "baseline_schema_version": BASELINE_SCHEMA_VERSION,
        "source_paths": {
            "run_dir": str(context["run_dir"]),
            "baseline_dir": str(context["baseline_dir"]),
        },
        "source_hashes": context["source_hashes"],
        "baseline_hash": context["baseline_hash"],
        "output_hashes": {
            scores_path.name: _sha256_path(scores_path),
            ranking_path.name: _sha256_path(ranking_path),
            comparison_path.name: _sha256_path(comparison_path),
            summary_path.name: _sha256_path(summary_path),
        },
        "configuration": {
            "weights": weights.as_dict(),
        },
        "generated_at": datetime.now(UTC).isoformat(),
        "gate_status": context["gate_status"],
        "allowed_languages": context["allowed_languages"],
        "warnings": context["warnings"],
        "provisional_status": context["provisional_status"],
        "activation_eligible": context["activation_eligible"],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    return {
        "gate_status": context["gate_status"],
        "provisional_status": context["provisional_status"],
        "activation_eligible": context["activation_eligible"],
        "allowed_languages": context["allowed_languages"],
        "shadow_rows": shadow_rows,
        "comparison_rows": comparison_rows,
        "summary": summary,
        "ranking": ranking_output,
        "output_dir": output_dir,
        "output_hashes": {
            scores_path.name: _sha256_path(scores_path),
            ranking_path.name: _sha256_path(ranking_path),
            comparison_path.name: _sha256_path(comparison_path),
            summary_path.name: _sha256_path(summary_path),
            manifest_path.name: _sha256_path(manifest_path),
        },
    }


def _load_shadow_context(*, run_dir: Path, baseline_dir: Path, requested_languages: list[str]) -> dict[str, Any]:
    input_paths = {
        "run_manifest.json": run_dir / "run_manifest.json",
        "movies.jsonl": run_dir / "movies.jsonl",
        "validation_summary.json": run_dir / "validation" / "validation_summary.json",
        "cohort_baselines.json": baseline_dir / "cohort_baselines.json",
        "movie_cohort_assignments.jsonl": baseline_dir / "movie_cohort_assignments.jsonl",
        "cohort_coverage_report.json": baseline_dir / "cohort_coverage_report.json",
    }
    required = {"run_manifest.json", "movies.jsonl", "cohort_baselines.json", "movie_cohort_assignments.jsonl", "cohort_coverage_report.json"}
    for name, path in input_paths.items():
        if name in required and not path.exists():
            raise FileNotFoundError(f"required file missing: {name}")

    run_manifest = _read_json(input_paths["run_manifest.json"])
    movies = _read_jsonl(input_paths["movies.jsonl"])
    validation_summary = _read_json(input_paths["validation_summary.json"]) if input_paths["validation_summary.json"].exists() else {}
    cohort_baselines = _read_json(input_paths["cohort_baselines.json"])
    assignments = _read_jsonl(input_paths["movie_cohort_assignments.jsonl"])
    coverage_report = _read_json(input_paths["cohort_coverage_report.json"])

    baseline_run_id = cohort_baselines.get("input_run_id")
    if baseline_run_id != run_manifest.get("run_id"):
        raise ValueError("baseline input_run_id does not match evidence run_id")

    gate_status, allowed_languages = _determine_gate_status(
        validation_summary=validation_summary,
        cohort_baselines=cohort_baselines,
        coverage_report=coverage_report,
    )
    provisional_status = _provisional_status_for_gate(gate_status)
    activation_eligible = False
    source_hashes = {name: _sha256_path(path) for name, path in input_paths.items() if path.exists()}
    baseline_hash = load_baseline_hash(input_paths["cohort_baselines.json"])
    assignments = sorted(assignments, key=lambda row: (row["original_language"], row["release_year"] if row["release_year"] is not None else 10**9, row["title"] or "", row["tmdb_movie_id"]))
    assignment_ids = {row["tmdb_movie_id"] for row in assignments}
    movies_by_id = {str(row["source_record_id"]): row for row in movies if str(row["source_record_id"]) in assignment_ids}
    if set(movies_by_id) != assignment_ids:
        raise ValueError("movie assignments do not match evidence movies")
    cohort_by_key = {row["cohort_key"]: row for row in cohort_baselines["cohort_records"]}
    cohort_samples = _build_cohort_samples(assignments)
    warnings: list[str] = []
    if provisional_status != APPROVED_FOR_SHADOW:
        warnings.append(provisional_status.casefold())
    if not input_paths["validation_summary.json"].exists():
        warnings.append("validation_summary_missing")
    return {
        "run_id": run_manifest["run_id"],
        "run_dir": run_dir,
        "baseline_dir": baseline_dir,
        "run_manifest": run_manifest,
        "validation_summary": validation_summary,
        "cohort_baselines": cohort_baselines,
        "assignments": assignments,
        "assignments_by_id": {row["tmdb_movie_id"]: row for row in assignments},
        "movies_by_id": movies_by_id,
        "cohort_by_key": cohort_by_key,
        "cohort_samples": cohort_samples,
        "gate_status": gate_status,
        "allowed_languages": sorted(allowed_languages),
        "requested_languages": sorted(set(requested_languages)),
        "provisional_status": provisional_status,
        "activation_eligible": activation_eligible,
        "source_hashes": source_hashes,
        "baseline_hash": baseline_hash,
        "warnings": warnings,
    }


def _determine_gate_status(
    *,
    validation_summary: dict[str, Any],
    cohort_baselines: dict[str, Any],
    coverage_report: dict[str, Any],
) -> tuple[str, set[str]]:
    recommendation = validation_summary.get("final_recommendation")
    languages = set(coverage_report["per_language_readiness"])
    if recommendation == BLOCKED_BY_ENTITY_RESOLUTION_QUALITY:
        return BLOCKED_BY_ENTITY_RESOLUTION_QUALITY, languages
    if recommendation == BLOCKED_BY_LOW_COVERAGE:
        return BLOCKED_BY_LOW_COVERAGE, languages

    review_status = cohort_baselines.get("review_status", {}).get("status")
    ready_languages = {
        language
        for language, row in coverage_report["per_language_readiness"].items()
        if row.get("readiness") == READINESS_READY
    }
    if review_status == "PENDING":
        return REVIEW_INPUT_REQUIRED, languages
    if review_status == "PARTIAL":
        return REVIEW_INPUT_INCOMPLETE, languages
    if ready_languages == languages and languages:
        return GO_FOR_ALL_LANGUAGES, languages
    if ready_languages:
        return GO_FOR_LIMITED_LANGUAGES, ready_languages
    return REVIEW_INPUT_REQUIRED, languages


def _provisional_status_for_gate(gate_status: str) -> str:
    if gate_status in {GO_FOR_ALL_LANGUAGES, GO_FOR_LIMITED_LANGUAGES}:
        return APPROVED_FOR_SHADOW
    if gate_status in {BLOCKED_BY_ENTITY_RESOLUTION_QUALITY, BLOCKED_BY_LOW_COVERAGE}:
        return BLOCKED_FROM_DATA_APPROVAL
    return PROVISIONAL_SHADOW_ONLY


def _build_cohort_samples(assignments: list[dict[str, Any]]) -> dict[str, CohortSignalSamples]:
    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in assignments:
        for key_name in ("level_1_cohort_key", "level_2_cohort_key", "level_3_cohort_key", "global_cohort_key"):
            cohort_key = row[key_name]
            for signal_name in ("tmdb_rating_normalized", "tmdb_vote_count_log1p", "tmdb_popularity_log1p"):
                value = row["signal_values"][signal_name]["value"]
                if value is not None:
                    grouped[cohort_key][signal_name].append(float(value))
    return {
        cohort_key: CohortSignalSamples(
            rating_normalized=tuple(sorted(values.get("tmdb_rating_normalized", []))),
            vote_count_log1p=tuple(sorted(values.get("tmdb_vote_count_log1p", []))),
            popularity_log1p=tuple(sorted(values.get("tmdb_popularity_log1p", []))),
        )
        for cohort_key, values in grouped.items()
    }


def _blocked_language_row(
    *,
    assignment: dict[str, Any],
    baseline_hash: str,
    gate_status: str,
    activation_eligible: bool,
) -> dict[str, Any]:
    return {
        "score_version": SCORE_VERSION,
        "baseline_version": BASELINE_SCHEMA_VERSION,
        "baseline_hash": baseline_hash,
        "tmdb_movie_id": assignment["tmdb_movie_id"],
        "cohort_key": assignment.get("selected_eligible_cohort_key"),
        "cohort_level": assignment.get("selected_eligible_cohort_level") or "unavailable",
        "cohort_sample_size": 0,
        "cohort_fallback_path": [
            assignment.get("level_1_cohort_key"),
            assignment.get("level_2_cohort_key"),
            assignment.get("level_3_cohort_key"),
            assignment.get("global_cohort_key"),
            "unavailable",
        ],
        "quality_component": None,
        "vote_reach_component": None,
        "popularity_reach_component": None,
        "confidence_component": None,
        "contextual_relevance": None,
        "original_weights": ShadowScoreWeights().as_dict(),
        "active_weights": {},
        "missing_components": ["quality", "vote_reach", "popularity_reach", "confidence"],
        "warnings": [f"blocked_language:{gate_status}"],
        "diagnostic_flags": ["BLOCKED_LANGUAGE"],
        "raw_total": None,
        "display_total": None,
        "activation_eligible": activation_eligible,
        "provisional_status": BLOCKED_FROM_DATA_APPROVAL,
    }


def _compute_v1_proxy(*, movie: dict[str, Any]) -> dict[str, Any]:
    missing_signals = ["critic_consensus"]
    if movie.get("vote_average") is None:
        missing_signals.append("audience_reception")
    if movie.get("popularity") is None:
        missing_signals.append("popularity")
    score = compute_cine_score_v1(
        normalized_query=str(movie.get("normalized_title") or ""),
        canonical_title=str(movie.get("normalized_title") or ""),
        release_year=movie.get("release_year"),
        requested_year=movie.get("release_year"),
        vote_average=movie.get("vote_average"),
        vote_count=movie.get("vote_count"),
        popularity=movie.get("popularity"),
        missing_signals=missing_signals,
    )
    return {
        "tmdb_movie_id": str(movie["source_record_id"]),
        "comparison_mode": "context_free_exact_match_proxy",
        "warning": "v1_query_context_unavailable_proxy_used",
        "score": score,
    }


def _build_shadow_ranking(
    *,
    shadow_rows: list[dict[str, Any]],
    assignments_by_id: dict[str, dict[str, Any]],
    movies_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    ordered = _order_shadow_rows(shadow_rows=shadow_rows, assignments_by_id=assignments_by_id, movies_by_id=movies_by_id)
    by_language: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(ordered, start=1):
        assignment = assignments_by_id[row["tmdb_movie_id"]]
        by_language[assignment["original_language"]].append(
            {
                "rank": len(by_language[assignment["original_language"]]) + 1,
                "tmdb_movie_id": row["tmdb_movie_id"],
                "display_total": row["display_total"],
                "cohort_level": row["cohort_level"],
            }
        )
    return {
        "overall": [
            {
                "rank": index,
                "tmdb_movie_id": row["tmdb_movie_id"],
                "display_total": row["display_total"],
                "cohort_level": row["cohort_level"],
            }
            for index, row in enumerate(ordered, start=1)
        ],
        "by_language": {language: rows for language, rows in sorted(by_language.items())},
    }


def _build_comparisons(
    *,
    shadow_rows: list[dict[str, Any]],
    v1_proxy_rows: list[dict[str, Any]],
    assignments_by_id: dict[str, dict[str, Any]],
    movies_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    v1_by_id = {row["tmdb_movie_id"]: row for row in v1_proxy_rows}
    v1_ordered = sorted(
        v1_proxy_rows,
        key=lambda row: (
            -row["score"]["total"],
            movies_by_id[row["tmdb_movie_id"]].get("provider_position", 10**9),
            row["tmdb_movie_id"],
        ),
    )
    v2_ordered = _order_shadow_rows(shadow_rows=shadow_rows, assignments_by_id=assignments_by_id, movies_by_id=movies_by_id)
    v1_ranks = {row["tmdb_movie_id"]: index for index, row in enumerate(v1_ordered, start=1)}
    v2_ranks = {row["tmdb_movie_id"]: index for index, row in enumerate(v2_ordered, start=1)}
    comparison_rows = []
    for shadow_row in shadow_rows:
        tmdb_movie_id = shadow_row["tmdb_movie_id"]
        v1_proxy = v1_by_id[tmdb_movie_id]
        assignment = assignments_by_id[tmdb_movie_id]
        v1_score = v1_proxy["score"]["total"]
        v2_score = shadow_row["display_total"]
        v1_rank = v1_ranks.get(tmdb_movie_id)
        v2_rank = v2_ranks.get(tmdb_movie_id)
        rank_delta = (v1_rank - v2_rank) if v1_rank is not None and v2_rank is not None else None
        flags = _comparison_flags(
            shadow_row=shadow_row,
            rank_delta=rank_delta,
            assignment=assignment,
        )
        comparison_rows.append(
            {
                "tmdb_movie_id": tmdb_movie_id,
                "v1_score": v1_score,
                "v1_score_version": "cine-score-v1",
                "v1_comparison_mode": v1_proxy["comparison_mode"],
                "v2_shadow_score": v2_score,
                "v2_score_version": SCORE_VERSION,
                "v1_rank": v1_rank,
                "v2_rank": v2_rank,
                "rank_delta": rank_delta,
                "score_delta": round(v2_score - v1_score, 2) if v2_score is not None else None,
                "score_delta_label": "display_0_to_100_proxy_vs_shadow",
                "cohort_key": shadow_row["cohort_key"],
                "cohort_level": shadow_row["cohort_level"],
                "warnings": sorted(set(shadow_row["warnings"] + [v1_proxy["warning"]])),
                "flags": flags,
            }
        )
    comparison_rows.sort(key=lambda row: (assignments_by_id[row["tmdb_movie_id"]]["original_language"], row["tmdb_movie_id"]))
    return comparison_rows


def _comparison_flags(*, shadow_row: dict[str, Any], rank_delta: int | None, assignment: dict[str, Any]) -> list[str]:
    flags: list[str] = list(shadow_row["diagnostic_flags"])
    quality = shadow_row["quality_component"]
    vote_reach = shadow_row["vote_reach_component"]
    popularity_reach = shadow_row["popularity_reach_component"]
    reach_average = None
    reach_values = [value for value in (vote_reach, popularity_reach) if value is not None]
    if reach_values:
        reach_average = sum(reach_values) / len(reach_values)
    if rank_delta is not None and abs(rank_delta) >= 5:
        flags.append("LARGE_RANK_MOVEMENT")
    if rank_delta is not None and rank_delta >= 5 and quality is not None and quality >= 0.75 and reach_average is not None and reach_average < 0.4:
        flags.append("HIGH_QUALITY_LOW_REACH_MOVED_UP")
    if rank_delta is not None and rank_delta <= -5 and quality is not None and quality < 0.6 and reach_average is not None and reach_average >= 0.75:
        flags.append("HIGH_REACH_LOWER_QUALITY_MOVED_DOWN")
    if assignment.get("selected_eligible_cohort_level") == "level_4":
        flags.append("GLOBAL_FALLBACK_USED")
    if assignment.get("selected_eligible_cohort_level") == "level_3":
        flags.append("LANGUAGE_FALLBACK_USED")
    return sorted(set(flags))


def _build_summary(
    *,
    shadow_rows: list[dict[str, Any]],
    comparison_rows: list[dict[str, Any]],
    assignments_by_id: dict[str, dict[str, Any]],
    gate_status: str,
    provisional_status: str,
    activation_eligible: bool,
    allowed_languages: list[str],
) -> dict[str, Any]:
    scorable = [row for row in shadow_rows if row["display_total"] is not None]
    rank_deltas = [abs(row["rank_delta"]) for row in comparison_rows if row["rank_delta"] is not None]
    spearman = _spearman(comparison_rows)
    top10_overlap = _top_overlap(comparison_rows, limit=10)
    top20_overlap = _top_overlap(comparison_rows, limit=20)
    by_language: dict[str, list[int]] = defaultdict(list)
    by_level: dict[str, list[int]] = defaultdict(list)
    low_vote_movements: list[int] = []
    high_vote_movements: list[int] = []
    vote_threshold = median([
        row["v1_score"]
        for row in comparison_rows
        if row["v1_score"] is not None
    ]) if comparison_rows else 0.0
    for row in comparison_rows:
        if row["rank_delta"] is None:
            continue
        language = assignments_by_id[row["tmdb_movie_id"]]["original_language"]
        by_language[language].append(abs(row["rank_delta"]))
        by_level[row["cohort_level"]].append(abs(row["rank_delta"]))
        if row["v1_score"] <= vote_threshold:
            low_vote_movements.append(abs(row["rank_delta"]))
        else:
            high_vote_movements.append(abs(row["rank_delta"]))
    top_movers_up = sorted(
        [row for row in comparison_rows if row["rank_delta"] is not None and row["rank_delta"] > 0],
        key=lambda row: (-row["rank_delta"], row["tmdb_movie_id"]),
    )[:5]
    top_movers_down = sorted(
        [row for row in comparison_rows if row["rank_delta"] is not None and row["rank_delta"] < 0],
        key=lambda row: (row["rank_delta"], row["tmdb_movie_id"]),
    )[:5]
    unchanged = [row for row in comparison_rows if row["rank_delta"] == 0]
    return {
        "movies_processed": len(shadow_rows),
        "v2_scorable_count": len(scorable),
        "unscorable_count": len(shadow_rows) - len(scorable),
        "language_counts": dict(sorted(Counter(assignments_by_id[row["tmdb_movie_id"]]["original_language"] for row in comparison_rows).items())),
        "cohort_level_distribution": dict(sorted(Counter(row["cohort_level"] for row in shadow_rows).items())),
        "fallback_distribution": dict(sorted(Counter(row["cohort_level"] for row in shadow_rows).items())),
        "missing_signal_distribution": dict(sorted(Counter(component for row in shadow_rows for component in row["missing_components"]).items())),
        "signal_coverage": {
            "quality_component": _coverage(shadow_rows, "quality_component"),
            "vote_reach_component": _coverage(shadow_rows, "vote_reach_component"),
            "popularity_reach_component": _coverage(shadow_rows, "popularity_reach_component"),
            "confidence_component": _coverage(shadow_rows, "confidence_component"),
        },
        "v1_v2_metrics": {
            "spearman_rank_correlation": spearman,
            "top_10_overlap": top10_overlap,
            "top_20_overlap": top20_overlap,
            "average_absolute_rank_movement": round(sum(rank_deltas) / len(rank_deltas), 4) if rank_deltas else None,
            "median_absolute_rank_movement": round(median(rank_deltas), 4) if rank_deltas else None,
            "maximum_rank_movement": max(rank_deltas) if rank_deltas else None,
            "moved_up_by_at_least_5": sum(1 for row in comparison_rows if (row["rank_delta"] or 0) >= 5),
            "moved_down_by_at_least_5": sum(1 for row in comparison_rows if (row["rank_delta"] or 0) <= -5),
            "rank_movement_by_language": {key: round(sum(values) / len(values), 4) for key, values in sorted(by_language.items()) if values},
            "rank_movement_by_cohort_level": {key: round(sum(values) / len(values), 4) for key, values in sorted(by_level.items()) if values},
            "rank_movement_low_vote_proxy": round(sum(low_vote_movements) / len(low_vote_movements), 4) if low_vote_movements else None,
            "rank_movement_high_vote_proxy": round(sum(high_vote_movements) / len(high_vote_movements), 4) if high_vote_movements else None,
            "popularity_dominated_films_moving_down": sum(1 for row in comparison_rows if "HIGH_REACH_LOWER_QUALITY_MOVED_DOWN" in row["flags"]),
            "high_rating_lower_reach_films_moving_up": sum(1 for row in comparison_rows if "HIGH_QUALITY_LOW_REACH_MOVED_UP" in row["flags"]),
        },
        "top_movers_up": top_movers_up,
        "top_movers_down": top_movers_down,
        "unchanged_records": len(unchanged),
        "provisional_status": provisional_status,
        "activation_eligible": activation_eligible,
        "recommendation": provisional_status,
        "gate_status": gate_status,
        "allowed_languages": allowed_languages,
    }


def _spearman(comparison_rows: list[dict[str, Any]]) -> float | None:
    paired = [(row["v1_rank"], row["v2_rank"]) for row in comparison_rows if row["v1_rank"] is not None and row["v2_rank"] is not None]
    count = len(paired)
    if count < 2:
        return None
    diff_squared = sum((v1 - v2) ** 2 for v1, v2 in paired)
    return round(1 - ((6 * diff_squared) / (count * ((count ** 2) - 1))), 6)


def _top_overlap(comparison_rows: list[dict[str, Any]], *, limit: int) -> dict[str, Any]:
    v1 = {row["tmdb_movie_id"] for row in comparison_rows if row["v1_rank"] is not None and row["v1_rank"] <= limit}
    v2 = {row["tmdb_movie_id"] for row in comparison_rows if row["v2_rank"] is not None and row["v2_rank"] <= limit}
    overlap = v1 & v2
    return {
        "count": len(overlap),
        "limit": limit,
        "v1_count": len(v1),
        "v2_count": len(v2),
        "overlap_ids": sorted(overlap),
    }


def _coverage(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    count = sum(1 for row in rows if row[key] is not None)
    return {"count": count, "denominator": len(rows), "percentage": round(count / len(rows), 4) if rows else None}


def _order_shadow_rows(
    *,
    shadow_rows: list[dict[str, Any]],
    assignments_by_id: dict[str, dict[str, Any]],
    movies_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(
        shadow_rows,
        key=lambda row: (
            row["raw_total"] is None,
            -(row["raw_total"] if row["raw_total"] is not None else -1),
            -(row["quality_component"] if row["quality_component"] is not None else -1),
            -(row["confidence_component"] if row["confidence_component"] is not None else -1),
            movies_by_id[row["tmdb_movie_id"]].get("provider_position", 10**9),
            row["tmdb_movie_id"],
        ),
    )


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"json file must contain an object: {path.name}")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"jsonl row must be an object in {path.name} line {line_number}")
        rows.append(payload)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
