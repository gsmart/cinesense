from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from app.core.config import Settings
from app.regional_cohort_baselines import BASELINE_SCHEMA_VERSION
from app.regional_evidence_validation import ACCEPTED_REVIEW_DECISIONS, SOURCE_ERROR
from app.regional_shadow_scoring import (
    APPROVED_FOR_SHADOW,
    BLOCKED_BY_ENTITY_RESOLUTION_QUALITY,
    BLOCKED_BY_LOW_COVERAGE,
    GO_FOR_ALL_LANGUAGES,
    GO_FOR_LIMITED_LANGUAGES,
    REVIEW_INPUT_INCOMPLETE,
    REVIEW_INPUT_REQUIRED,
)

EVALUATION_SCHEMA_VERSION = "regional-shadow-evaluation-v1"
DEFAULT_OUTPUT_ROOT = Path("/tmp/cinesense-regional-evaluation")
EVALUATION_MODE_DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
EVALUATION_MODE_HUMAN_JUDGMENT = "HUMAN_JUDGMENT"
PHASE_READY_ALL = "READY_FOR_HUMAN_RANKING_EVALUATION"
PHASE_READY_LIMITED = "READY_FOR_LIMITED_LANGUAGE_HUMAN_EVALUATION"
PHASE_DIAGNOSTIC_ONLY = "DIAGNOSTIC_EVALUATION_COMPLETE"
PHASE_BLOCKED_REGRESSION = "BLOCKED_BY_EVALUATION_REGRESSION"
PHASE_BLOCKED_INVALID_INPUT = "BLOCKED_BY_INVALID_INPUT"
SEVERITY_BLOCKING = "BLOCKING"
SEVERITY_WARNING = "WARNING"
SEVERITY_INFORMATIONAL = "INFORMATIONAL"
REQUIRED_JUDGMENT_COLUMNS = (
    "evaluation_case_id",
    "query_or_context",
    "tmdb_movie_id",
    "language",
    "relevance_grade",
    "quality_grade",
    "confidence_in_judgment",
    "reviewer_notes",
)
ALLOWED_GRADE_VALUES = {"0", "1", "2", "3"}
ALLOWED_JUDGMENT_CONFIDENCE = {"LOW", "MEDIUM", "HIGH"}
INTRINSIC_COMPONENT_NAMES = ("quality_component", "vote_reach_component", "popularity_reach_component")
SCORED_WEIGHT_COMPONENT_NAMES = ("quality", "vote_reach", "popularity_reach", "confidence")


def evaluate_regional_shadow_ranking(
    *,
    shadow_dir: Path,
    output_dir: Path | None = None,
    judgment_file: Path | None = None,
) -> dict[str, Any]:
    context = _load_evaluation_context(shadow_dir=Path(shadow_dir).resolve(), judgment_file=judgment_file)
    output_dir = (Path(output_dir).resolve() if output_dir else (DEFAULT_OUTPUT_ROOT / context["shadow_run_id"]).resolve())
    output_dir.mkdir(parents=True, exist_ok=True)

    cases, regressions = _build_cases_and_regressions(context)
    regression_summary = _summarize_regressions(regressions)
    language_comparison = _build_language_comparison(cases)
    diagnostic_metrics = _build_diagnostic_metrics(cases)
    fallback_metrics = _build_fallback_metrics(cases)
    confidence_metrics = _build_confidence_metrics(cases)
    missing_data_metrics = _build_missing_data_metrics(cases)
    human_metrics = _build_human_metrics(cases, context["evaluation_mode"])
    phase_recommendation = _phase_recommendation(
        regression_summary=regression_summary,
        gate_status=context["gate_status"],
    )

    summary = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "evaluation_mode": context["evaluation_mode"],
        "score_version": context["score_version"],
        "baseline_version": context["baseline_version"],
        "source_hashes": context["source_hashes"],
        "movie_counts": {
            "evaluated": len(cases),
            "v1_scorable_count": sum(1 for case in cases if case["v1_score"] is not None),
            "v2_scorable_count": sum(1 for case in cases if case["v2_score"] is not None),
        },
        "diagnostic_metrics": diagnostic_metrics,
        "language_metrics": language_comparison,
        "fallback_metrics": fallback_metrics,
        "confidence_metrics": confidence_metrics,
        "missing_data_metrics": missing_data_metrics,
        "regression_counts": regression_summary,
        "human_judgment_metrics": human_metrics,
        "phase_recommendation": phase_recommendation,
        "evidence_gate": context["gate_status"],
        "review_status": context["review_status"],
        "allowed_languages": context["allowed_languages"],
        "warnings": context["warnings"],
    }

    regressions_output = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "blocking_regressions": regressions[SEVERITY_BLOCKING],
        "warnings": regressions[SEVERITY_WARNING],
        "informational_findings": regressions[SEVERITY_INFORMATIONAL],
        "affected_movie_ids": {
            severity.casefold(): sorted(
                {
                    movie_id
                    for finding in findings
                    for movie_id in finding.get("affected_movie_ids", [])
                }
            )
            for severity, findings in regressions.items()
        },
    }

    manifest = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_paths": context["source_paths"],
        "source_hashes": context["source_hashes"],
        "configuration": {
            "judgment_file": str(context["judgment_file"]) if context["judgment_file"] else None,
            "confidence_bands": {
                "low": "confidence < 0.50",
                "medium": "0.50 <= confidence < 0.75",
                "high": "confidence >= 0.75",
            },
            "movement_thresholds": {
                "large": 5,
                "very_large": 10,
            },
        },
        "evaluation_mode": context["evaluation_mode"],
        "evidence_gate": context["gate_status"],
        "review_state": context["review_status"],
        "allowed_languages": context["allowed_languages"],
        "warnings": context["warnings"],
    }

    summary_path = output_dir / "evaluation_summary.json"
    cases_path = output_dir / "evaluation_cases.jsonl"
    regressions_path = output_dir / "evaluation_regressions.json"
    language_path = output_dir / "language_comparison.json"
    manifest_path = output_dir / "evaluation_manifest.json"

    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    _write_jsonl(cases_path, cases)
    regressions_path.write_text(json.dumps(regressions_output, indent=2, sort_keys=True), encoding="utf-8")
    language_path.write_text(json.dumps(language_comparison, indent=2, sort_keys=True), encoding="utf-8")
    manifest["output_hashes"] = {
        summary_path.name: _sha256_path(summary_path),
        cases_path.name: _sha256_path(cases_path),
        regressions_path.name: _sha256_path(regressions_path),
        language_path.name: _sha256_path(language_path),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    return {
        "summary": summary,
        "cases": cases,
        "regressions": regressions_output,
        "language_comparison": language_comparison,
        "output_dir": output_dir,
        "output_hashes": {
            summary_path.name: _sha256_path(summary_path),
            cases_path.name: _sha256_path(cases_path),
            regressions_path.name: _sha256_path(regressions_path),
            language_path.name: _sha256_path(language_path),
            manifest_path.name: _sha256_path(manifest_path),
        },
    }


def _load_evaluation_context(*, shadow_dir: Path, judgment_file: Path | None) -> dict[str, Any]:
    required_paths = {
        "shadow_manifest.json": shadow_dir / "shadow_manifest.json",
        "shadow_scores.jsonl": shadow_dir / "shadow_scores.jsonl",
        "shadow_ranking.json": shadow_dir / "shadow_ranking.json",
        "shadow_summary.json": shadow_dir / "shadow_summary.json",
        "v1_v2_comparison.json": shadow_dir / "v1_v2_comparison.json",
    }
    for name, path in required_paths.items():
        if not path.exists():
            raise ValueError(f"missing required shadow artifact: {name}")

    manifest = _read_json(required_paths["shadow_manifest.json"])
    shadow_rows = _read_jsonl(required_paths["shadow_scores.jsonl"])
    ranking = _read_json(required_paths["shadow_ranking.json"])
    summary = _read_json(required_paths["shadow_summary.json"])
    comparison = _read_json(required_paths["v1_v2_comparison.json"])
    source_paths = manifest.get("source_paths", {})
    run_dir = Path(source_paths.get("run_dir", "")).resolve()
    baseline_dir = Path(source_paths.get("baseline_dir", "")).resolve()
    if not run_dir.exists() or not baseline_dir.exists():
        raise ValueError("shadow source_paths are incomplete or missing on disk")

    evidence_paths = {
        "run_manifest.json": run_dir / "run_manifest.json",
        "movies.jsonl": run_dir / "movies.jsonl",
        "validation_summary.json": run_dir / "validation" / "validation_summary.json",
        "cohort_baselines.json": baseline_dir / "cohort_baselines.json",
        "movie_cohort_assignments.jsonl": baseline_dir / "movie_cohort_assignments.jsonl",
        "cohort_coverage_report.json": baseline_dir / "cohort_coverage_report.json",
    }
    required_evidence = (
        "run_manifest.json",
        "movies.jsonl",
        "cohort_baselines.json",
        "movie_cohort_assignments.jsonl",
        "cohort_coverage_report.json",
    )
    for name in required_evidence:
        if not evidence_paths[name].exists():
            raise ValueError(f"missing required source artifact: {name}")

    run_manifest = _read_json(evidence_paths["run_manifest.json"])
    movies = _read_jsonl(evidence_paths["movies.jsonl"])
    validation_summary = _read_json(evidence_paths["validation_summary.json"]) if evidence_paths["validation_summary.json"].exists() else {}
    cohort_baselines = _read_json(evidence_paths["cohort_baselines.json"])
    assignments = _read_jsonl(evidence_paths["movie_cohort_assignments.jsonl"])
    coverage_report = _read_json(evidence_paths["cohort_coverage_report.json"])

    judgment_rows = _load_judgments(judgment_file=judgment_file, shadow_rows=shadow_rows)
    source_hashes = {
        "shadow_manifest.json": _sha256_path(required_paths["shadow_manifest.json"]),
        "shadow_scores.jsonl": _sha256_path(required_paths["shadow_scores.jsonl"]),
        "shadow_ranking.json": _sha256_path(required_paths["shadow_ranking.json"]),
        "shadow_summary.json": _sha256_path(required_paths["shadow_summary.json"]),
        "v1_v2_comparison.json": _sha256_path(required_paths["v1_v2_comparison.json"]),
        "run_manifest.json": _sha256_path(evidence_paths["run_manifest.json"]),
        "movies.jsonl": _sha256_path(evidence_paths["movies.jsonl"]),
        "cohort_baselines.json": _sha256_path(evidence_paths["cohort_baselines.json"]),
        "movie_cohort_assignments.jsonl": _sha256_path(evidence_paths["movie_cohort_assignments.jsonl"]),
        "cohort_coverage_report.json": _sha256_path(evidence_paths["cohort_coverage_report.json"]),
    }
    if evidence_paths["validation_summary.json"].exists():
        source_hashes["validation_summary.json"] = _sha256_path(evidence_paths["validation_summary.json"])
    if judgment_file is not None:
        source_hashes["judgment_file"] = _sha256_path(judgment_file)

    return {
        "shadow_dir": shadow_dir,
        "shadow_run_id": run_manifest["run_id"],
        "shadow_rows": shadow_rows,
        "ranking": ranking,
        "comparison_rows": comparison["rows"],
        "summary": summary,
        "run_manifest": run_manifest,
        "movies_by_id": {str(row["source_record_id"]): row for row in movies},
        "assignments_by_id": {str(row["tmdb_movie_id"]): row for row in assignments},
        "cohort_baselines": cohort_baselines,
        "cohort_by_key": {row["cohort_key"]: row for row in cohort_baselines["cohort_records"]},
        "coverage_report": coverage_report,
        "validation_summary": validation_summary,
        "source_paths": {
            "shadow_dir": str(shadow_dir),
            "run_dir": str(run_dir),
            "baseline_dir": str(baseline_dir),
        },
        "source_hashes": source_hashes,
        "judgments_by_movie_id": judgment_rows,
        "judgment_file": judgment_file,
        "evaluation_mode": EVALUATION_MODE_HUMAN_JUDGMENT if judgment_file else EVALUATION_MODE_DIAGNOSTIC_ONLY,
        "score_version": manifest.get("score_version"),
        "baseline_version": manifest.get("baseline_schema_version", BASELINE_SCHEMA_VERSION),
        "gate_status": manifest.get("gate_status"),
        "review_status": cohort_baselines.get("review_status", {}).get("status"),
        "allowed_languages": manifest.get("allowed_languages", []),
        "warnings": sorted(set(manifest.get("warnings", []))),
    }


def _build_cases_and_regressions(context: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    shadow_rows = context["shadow_rows"]
    assignments_by_id = context["assignments_by_id"]
    movies_by_id = context["movies_by_id"]
    comparison_by_id = {row["tmdb_movie_id"]: row for row in context["comparison_rows"]}
    ranking_overall = context["ranking"]["overall"]
    regressions: dict[str, list[dict[str, Any]]] = {
        SEVERITY_BLOCKING: [],
        SEVERITY_WARNING: [],
        SEVERITY_INFORMATIONAL: [],
    }

    shadow_ids = [str(row["tmdb_movie_id"]) for row in shadow_rows]
    duplicate_shadow_ids = sorted(movie_id for movie_id, count in Counter(shadow_ids).items() if count > 1)
    if duplicate_shadow_ids:
        _add_regression(
            regressions,
            severity=SEVERITY_BLOCKING,
            code="DUPLICATE_MOVIE_IDS",
            message="shadow output contains duplicate tmdb movie ids",
            affected_movie_ids=duplicate_shadow_ids,
            evidence={"duplicate_ids": duplicate_shadow_ids},
        )

    missing_assignment_ids = sorted(movie_id for movie_id in shadow_ids if movie_id not in assignments_by_id)
    if missing_assignment_ids:
        _add_regression(
            regressions,
            severity=SEVERITY_BLOCKING,
            code="MISSING_ASSIGNMENTS",
            message="shadow rows are missing assignment rows",
            affected_movie_ids=missing_assignment_ids,
            evidence={"missing_assignment_ids": missing_assignment_ids},
        )

    if Settings().active_ranking_version != "cine-score-v1":
        _add_regression(
            regressions,
            severity=SEVERITY_BLOCKING,
            code="ACTIVE_RANKING_VERSION_CHANGED",
            message="active ranking version is not cine-score-v1",
            affected_movie_ids=[],
            evidence={"active_ranking_version": Settings().active_ranking_version},
        )

    if context["score_version"] != "cine-score-v2-shadow-1":
        _add_regression(
            regressions,
            severity=SEVERITY_WARNING,
            code="UNEXPECTED_SCORE_VERSION",
            message="evaluation input score version differs from the expected shadow version",
            affected_movie_ids=[],
            evidence={"score_version": context["score_version"]},
        )

    overall_thresholds = _overall_thresholds(assignments_by_id.values())
    cases = []
    for row in shadow_rows:
        movie_id = row["tmdb_movie_id"]
        assignment = assignments_by_id.get(movie_id)
        movie = movies_by_id.get(movie_id)
        comparison = comparison_by_id.get(movie_id)
        if assignment is None or movie is None or comparison is None:
            continue
        language = assignment["original_language"]
        cohort_record = context["cohort_by_key"].get(row["cohort_key"]) if row.get("cohort_key") else None
        thresholds = _thresholds_for_assignment(assignment=assignment, cohort_record=cohort_record, overall_thresholds=overall_thresholds)
        reach_average = _average([row["vote_reach_component"], row["popularity_reach_component"]])
        quality_group = _band_from_component(row["quality_component"])
        reach_group = _band_from_component(reach_average)
        vote_group = _group_from_thresholds(
            assignment["signal_values"]["tmdb_vote_count_log1p"]["value"],
            thresholds["vote"],
        )
        popularity_group = _group_from_thresholds(
            assignment["signal_values"]["tmdb_popularity_log1p"]["value"],
            thresholds["popularity"],
        )
        rating_group = _group_from_thresholds(
            assignment["signal_values"]["tmdb_rating_normalized"]["value"],
            thresholds["rating"],
        )
        confidence_band = _confidence_band(row["confidence_component"])
        intrinsic_count = sum(1 for name in INTRINSIC_COMPONENT_NAMES if row[name] is not None)
        active_weight_sum = round(sum(row["active_weights"].values()), 6) if row["active_weights"] else 0.0
        renormalized = bool(row["active_weights"]) and (
            intrinsic_count < 3
            or row["confidence_component"] is None
            or any(
                not math.isclose(row["active_weights"].get(name, 0.0), row["original_weights"].get(name, 0.0), abs_tol=1e-6)
                for name in row["original_weights"]
            )
        )
        single_signal = intrinsic_count == 1 and row["raw_total"] is not None
        case_regression_flags: list[str] = []
        if row["raw_total"] is not None and not (0.0 <= row["raw_total"] <= 1.0):
            case_regression_flags.append("INVALID_RAW_SCORE_RANGE")
        if row["display_total"] is not None and not (0.0 <= row["display_total"] <= 100.0):
            case_regression_flags.append("INVALID_DISPLAY_SCORE_RANGE")
        if row["active_weights"] and not math.isclose(active_weight_sum, 1.0, abs_tol=1e-6):
            case_regression_flags.append("INVALID_ACTIVE_WEIGHT_SUM")
        expected_total = _recompute_shadow_total(row)
        if expected_total is not None and not math.isclose(expected_total, row["raw_total"], abs_tol=2e-6):
            case_regression_flags.append("DIAGNOSTIC_FLAGS_AFFECT_SCORE")
        if row["cohort_level"] == "unavailable" and row["raw_total"] is not None:
            case_regression_flags.append("UNAVAILABLE_COHORT_SCORED")
        if assignment.get("review_decision") == "REJECTED" and assignment["signal_eligibility_flags"].get("wikidata_identity"):
            case_regression_flags.append("REJECTED_EVIDENCE_USES_WIKIDATA_IDENTITY")
        if assignment.get("entity_resolution_status") == SOURCE_ERROR and assignment["signal_eligibility_flags"].get("wikidata_identity"):
            case_regression_flags.append("SOURCE_ERROR_USES_WIKIDATA_IDENTITY")
        if row["raw_total"] is None:
            case_regression_flags.append("UNSCORABLE")
        if renormalized:
            case_regression_flags.append("HEAVY_WEIGHT_RENORMALIZATION")
        if single_signal:
            case_regression_flags.append("SINGLE_SIGNAL_SCORE")
        if row["quality_component"] is None:
            case_regression_flags.append("MISSING_QUALITY")
        if row["vote_reach_component"] is None and row["popularity_reach_component"] is None:
            case_regression_flags.append("MISSING_REACH")

        judgment = context["judgments_by_movie_id"].get(movie_id)
        cases.append(
            {
                "evaluation_case_id": movie_id,
                "tmdb_movie_id": movie_id,
                "title": movie.get("title"),
                "language": language,
                "release_year": assignment.get("release_year"),
                "primary_genre": assignment.get("primary_genre"),
                "era": assignment.get("era"),
                "provider_position": movie.get("provider_position"),
                "v1_rank": comparison.get("v1_rank"),
                "v2_rank": comparison.get("v2_rank"),
                "rank_delta": comparison.get("rank_delta"),
                "v1_score": comparison.get("v1_score"),
                "v2_score": row.get("display_total"),
                "quality": row.get("quality_component"),
                "vote_reach": row.get("vote_reach_component"),
                "popularity_reach": row.get("popularity_reach_component"),
                "confidence": row.get("confidence_component"),
                "reach_average": _round_float(reach_average),
                "selected_cohort_level": row.get("cohort_level"),
                "selected_cohort_key": row.get("cohort_key"),
                "entity_status": assignment.get("entity_resolution_status"),
                "manual_review_status": _manual_review_status(assignment),
                "fallback_specificity": row.get("cohort_level"),
                "quality_group": quality_group,
                "reach_group": reach_group,
                "vote_group": vote_group,
                "popularity_group": popularity_group,
                "rating_group": rating_group,
                "confidence_band": confidence_band,
                "intrinsic_component_count": intrinsic_count,
                "missing_components": sorted(row.get("missing_components", [])),
                "diagnostic_flags": sorted(set(row.get("diagnostic_flags", []))),
                "comparison_flags": sorted(set(comparison.get("flags", []))),
                "regression_flags": sorted(set(case_regression_flags)),
                "warnings": sorted(set(row.get("warnings", []) + comparison.get("warnings", []))),
                "judgment": judgment,
            }
        )

    cases.sort(
        key=lambda row: (
            row["language"],
            row["v2_rank"] is None,
            row["v2_rank"] if row["v2_rank"] is not None else 10**9,
            row["v1_rank"] if row["v1_rank"] is not None else 10**9,
            row["tmdb_movie_id"],
        )
    )

    expected_ranking_ids = [
        row["tmdb_movie_id"]
        for row in sorted(
            shadow_rows,
            key=lambda row: (
                row["raw_total"] is None,
                -(row["raw_total"] if row["raw_total"] is not None else -1.0),
                -(row["quality_component"] if row["quality_component"] is not None else -1.0),
                -(row["confidence_component"] if row["confidence_component"] is not None else -1.0),
                movies_by_id[row["tmdb_movie_id"]].get("provider_position", 10**9),
                row["tmdb_movie_id"],
            ),
        )
    ]
    actual_ranking_ids = [str(row["tmdb_movie_id"]) for row in ranking_overall]
    if actual_ranking_ids != expected_ranking_ids:
        _add_regression(
            regressions,
            severity=SEVERITY_BLOCKING,
            code="RANKING_ORDER_VIOLATION",
            message="shadow ranking order violates deterministic tie-breaking",
            affected_movie_ids=sorted(set(actual_ranking_ids) ^ set(expected_ranking_ids))[:20],
            evidence={"expected_first_10": expected_ranking_ids[:10], "actual_first_10": actual_ranking_ids[:10]},
        )

    if any(
        later["raw_total"] is not None and earlier["raw_total"] is None
        for earlier, later in zip(
            sorted(shadow_rows, key=lambda row: actual_ranking_ids.index(row["tmdb_movie_id"])),
            sorted(shadow_rows, key=lambda row: actual_ranking_ids.index(row["tmdb_movie_id"]))[1:],
        )
    ):
        _add_regression(
            regressions,
            severity=SEVERITY_BLOCKING,
            code="NULL_SCORE_SORT_ORDER",
            message="null-score records sort ahead of scored records",
            affected_movie_ids=[],
            evidence={"ranking_ids": actual_ranking_ids[:20]},
        )

    case_index = {case["tmdb_movie_id"]: case for case in cases}
    for case in cases:
        for flag in case["regression_flags"]:
            severity = (
                SEVERITY_WARNING
                if flag in {"HEAVY_WEIGHT_RENORMALIZATION", "SINGLE_SIGNAL_SCORE", "UNSCORABLE", "MISSING_QUALITY", "MISSING_REACH"}
                else SEVERITY_BLOCKING
            )
            _add_regression(
                regressions,
                severity=severity,
                code=flag,
                message=flag.casefold(),
                affected_movie_ids=[case["tmdb_movie_id"]],
                evidence={
                    "tmdb_movie_id": case["tmdb_movie_id"],
                    "title": case["title"],
                    "language": case["language"],
                },
            )

    if sorted(case_index) != sorted(shadow_ids):
        _add_regression(
            regressions,
            severity=SEVERITY_BLOCKING,
            code="EVALUATION_CASE_COUNT_MISMATCH",
            message="evaluation cases do not cover every shadow row exactly once",
            affected_movie_ids=sorted(set(shadow_ids) ^ set(case_index)),
            evidence={"shadow_count": len(shadow_ids), "case_count": len(cases)},
        )

    return cases, _deduplicate_regressions(regressions)


def _build_diagnostic_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    overall = _movement_metrics(cases)
    overall.update(
        {
            "kendall_tau_b": _kendall_tau_b(cases),
            "top_5_overlap": _top_overlap(cases, 5),
            "top_10_overlap": _top_overlap(cases, 10),
            "top_20_overlap": _top_overlap(cases, 20),
            "quality_reach_movement": _quality_reach_movements(cases),
            "regional_fairness": _regional_fairness(cases),
        }
    )
    return overall


def _build_language_comparison(cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_language: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        by_language[case["language"]].append(case)
    output = {}
    for language, rows in sorted(by_language.items()):
        output[language] = {
            "movie_count": len(rows),
            "rank_metrics": {
                **_movement_metrics(rows),
                "kendall_tau_b": _kendall_tau_b(rows),
                "top_5_overlap": _top_overlap(rows, 5),
                "top_10_overlap": _top_overlap(rows, 10),
                "top_20_overlap": _top_overlap(rows, 20),
            },
            "quality_reach_movement": _quality_reach_movements(rows),
            "fallback_usage": {
                "counts": dict(sorted(Counter(case["selected_cohort_level"] for case in rows).items())),
                "fallback_rate": _safe_rate(sum(1 for case in rows if case["selected_cohort_level"] != "level_1"), len(rows)),
            },
            "confidence_distribution": dict(sorted(Counter(case["confidence_band"] for case in rows).items())),
            "missing_signal_distribution": dict(sorted(Counter(component for case in rows for component in case["missing_components"]).items())),
            "average_quality_component": _average(case["quality"] for case in rows),
            "average_reach_component": _average(case["reach_average"] for case in rows),
            "average_confidence": _average(case["confidence"] for case in rows),
        }
    return output


def _build_fallback_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_level: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        by_level[case["selected_cohort_level"]].append(case)
    output = {}
    for level in ("level_1", "level_2", "level_3", "level_4", "unavailable"):
        rows = by_level.get(level, [])
        if not rows:
            output[level] = {
                "movie_count": 0,
                "scorable_count": 0,
                "average_v2_score": None,
                "average_confidence": None,
                "average_rank_movement": None,
                "median_rank_movement": None,
                "large_movement_rate": None,
                "missing_component_rate": None,
            }
            continue
        movements = [abs(case["rank_delta"]) for case in rows if case["rank_delta"] is not None]
        output[level] = {
            "movie_count": len(rows),
            "scorable_count": sum(1 for case in rows if case["v2_score"] is not None),
            "average_v2_score": _average(case["v2_score"] for case in rows),
            "average_confidence": _average(case["confidence"] for case in rows),
            "average_rank_movement": _average(movements),
            "median_rank_movement": _median(movements),
            "large_movement_rate": _safe_rate(sum(1 for case in rows if abs(case["rank_delta"] or 0) >= 5), len(rows)),
            "missing_component_rate": _safe_rate(sum(1 for case in rows if case["missing_components"]), len(rows)),
        }
    return output


def _build_confidence_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_band: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        by_band[case["confidence_band"]].append(case)
    output = {}
    for band in ("low", "medium", "high", "unknown"):
        rows = by_band.get(band, [])
        movements = [abs(case["rank_delta"]) for case in rows if case["rank_delta"] is not None]
        output[band] = {
            "movie_count": len(rows),
            "average_rank_movement": _average(movements),
            "median_rank_movement": _median(movements),
            "missing_signal_rate": _safe_rate(sum(1 for case in rows if case["missing_components"]), len(rows)),
            "fallback_distribution": dict(sorted(Counter(case["selected_cohort_level"] for case in rows).items())),
            "entity_status_distribution": dict(sorted(Counter(case["entity_status"] for case in rows).items())),
        }
    return output


def _build_missing_data_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    intrinsic_counts = Counter(case["intrinsic_component_count"] for case in cases if case["v2_score"] is not None)
    return {
        "missing_quality_count": sum(1 for case in cases if case["quality"] is None),
        "missing_vote_reach_count": sum(1 for case in cases if case["vote_reach"] is None),
        "missing_popularity_reach_count": sum(1 for case in cases if case["popularity_reach"] is None),
        "missing_confidence_count": sum(1 for case in cases if case["confidence"] is None),
        "null_total_count": sum(1 for case in cases if case["v2_score"] is None),
        "active_weight_renormalization_count": sum(1 for case in cases if "HEAVY_WEIGHT_RENORMALIZATION" in case["regression_flags"]),
        "single_intrinsic_component_count": intrinsic_counts.get(1, 0),
        "two_intrinsic_component_count": intrinsic_counts.get(2, 0),
        "all_three_intrinsic_component_count": intrinsic_counts.get(3, 0),
        "flag_counts": {
            "SINGLE_SIGNAL_SCORE": sum(1 for case in cases if "SINGLE_SIGNAL_SCORE" in case["regression_flags"]),
            "HEAVY_WEIGHT_RENORMALIZATION": sum(1 for case in cases if "HEAVY_WEIGHT_RENORMALIZATION" in case["regression_flags"]),
            "MISSING_QUALITY": sum(1 for case in cases if "MISSING_QUALITY" in case["regression_flags"]),
            "MISSING_REACH": sum(1 for case in cases if "MISSING_REACH" in case["regression_flags"]),
            "UNSCORABLE": sum(1 for case in cases if "UNSCORABLE" in case["regression_flags"]),
        },
    }


def _build_human_metrics(cases: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    if mode != EVALUATION_MODE_HUMAN_JUDGMENT:
        return {
            "status": "NOT_SUPPLIED_DIAGNOSTIC_ONLY",
            "overall": None,
            "per_language": {},
            "per_context": {},
        }
    judged = [case for case in cases if case["judgment"] is not None]
    by_language: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_context: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in judged:
        by_language[case["language"]].append(case)
        by_context[case["judgment"]["query_or_context"]].append(case)
    return {
        "status": "HUMAN_JUDGMENT_FILE_USED",
        "overall": _human_metric_block(judged),
        "per_language": {language: _human_metric_block(rows) for language, rows in sorted(by_language.items())},
        "per_context": {name: _human_metric_block(rows) for name, rows in sorted(by_context.items())},
    }


def _human_metric_block(cases: list[dict[str, Any]]) -> dict[str, Any]:
    if not cases:
        return {
            "count": 0,
            "v1": None,
            "v2": None,
            "delta": None,
        }
    return {
        "count": len(cases),
        "v1": _single_rank_metrics(cases, rank_key="v1_rank"),
        "v2": _single_rank_metrics(cases, rank_key="v2_rank"),
        "delta": _metric_delta(
            _single_rank_metrics(cases, rank_key="v1_rank"),
            _single_rank_metrics(cases, rank_key="v2_rank"),
        ),
    }


def _single_rank_metrics(cases: list[dict[str, Any]], *, rank_key: str) -> dict[str, Any]:
    ordered = sorted(cases, key=lambda case: (case[rank_key] is None, case[rank_key] if case[rank_key] is not None else 10**9, case["tmdb_movie_id"]))
    grades = [case["judgment"]["relevance_grade"] for case in ordered]
    relevant = [grade for grade in grades if grade >= 2]
    return {
        "ndcg_at_5": _ndcg(grades, 5),
        "ndcg_at_10": _ndcg(grades, 10),
        "ndcg_at_20": _ndcg(grades, 20),
        "precision_at_5": _precision_at_k(grades, 5),
        "precision_at_10": _precision_at_k(grades, 10),
        "recall_at_10": _recall_at_k(grades, 10, total_relevant=len(relevant)),
        "mean_reciprocal_rank": _mrr(grades),
        "pairwise_preference_accuracy": _pairwise_preference_accuracy(ordered, rank_key=rank_key),
    }


def _phase_recommendation(*, regression_summary: dict[str, int], gate_status: str | None) -> str:
    if regression_summary["blocking"] > 0:
        return PHASE_BLOCKED_REGRESSION
    if gate_status == GO_FOR_ALL_LANGUAGES:
        return PHASE_READY_ALL
    if gate_status == GO_FOR_LIMITED_LANGUAGES:
        return PHASE_READY_LIMITED
    if gate_status in {
        REVIEW_INPUT_REQUIRED,
        REVIEW_INPUT_INCOMPLETE,
        BLOCKED_BY_LOW_COVERAGE,
        BLOCKED_BY_ENTITY_RESOLUTION_QUALITY,
        None,
    }:
        return PHASE_DIAGNOSTIC_ONLY
    return PHASE_BLOCKED_INVALID_INPUT


def _movement_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    deltas = [case["rank_delta"] for case in cases if case["rank_delta"] is not None]
    absolute = [abs(delta) for delta in deltas]
    return {
        "movie_count": len(cases),
        "v1_scorable_count": sum(1 for case in cases if case["v1_score"] is not None),
        "v2_scorable_count": sum(1 for case in cases if case["v2_score"] is not None),
        "spearman_rank_correlation": _spearman(cases),
        "average_absolute_rank_movement": _average(absolute),
        "median_absolute_rank_movement": _median(absolute),
        "p90_absolute_rank_movement": _percentile_from_sorted(sorted(absolute), 90),
        "maximum_absolute_rank_movement": max(absolute) if absolute else None,
        "unchanged_count": sum(1 for delta in deltas if delta == 0),
        "moved_up_count": sum(1 for delta in deltas if delta > 0),
        "moved_down_count": sum(1 for delta in deltas if delta < 0),
        "moved_up_by_5_count": sum(1 for delta in deltas if delta >= 5),
        "moved_down_by_5_count": sum(1 for delta in deltas if delta <= -5),
        "moved_up_by_10_count": sum(1 for delta in deltas if delta >= 10),
        "moved_down_by_10_count": sum(1 for delta in deltas if delta <= -10),
    }


def _quality_reach_movements(cases: list[dict[str, Any]]) -> dict[str, Any]:
    categories = {
        "high_rating_low_reach_up": [],
        "high_rating_high_reach_up": [],
        "lower_rating_high_reach_down": [],
        "lower_rating_low_reach_down": [],
        "high_rating_down_unexpected": [],
        "low_rating_up_unexpected": [],
    }
    for case in cases:
        delta = case["rank_delta"]
        if delta is None:
            continue
        if case["quality_group"] == "high" and case["reach_group"] == "low" and delta > 0:
            categories["high_rating_low_reach_up"].append(case)
        if case["quality_group"] == "high" and case["reach_group"] == "high" and delta > 0:
            categories["high_rating_high_reach_up"].append(case)
        if case["quality_group"] == "low" and case["reach_group"] == "high" and delta < 0:
            categories["lower_rating_high_reach_down"].append(case)
        if case["quality_group"] == "low" and case["reach_group"] == "low" and delta < 0:
            categories["lower_rating_low_reach_down"].append(case)
        if case["quality_group"] == "high" and delta < 0:
            categories["high_rating_down_unexpected"].append(case)
        if case["quality_group"] == "low" and delta > 0:
            categories["low_rating_up_unexpected"].append(case)
    return {
        name: {
            "count": len(rows),
            "representative_records": [
                {
                    "tmdb_movie_id": row["tmdb_movie_id"],
                    "title": row["title"],
                    "language": row["language"],
                    "rank_delta": row["rank_delta"],
                    "v1_rank": row["v1_rank"],
                    "v2_rank": row["v2_rank"],
                }
                for row in sorted(rows, key=lambda item: (-abs(item["rank_delta"]), item["tmdb_movie_id"]))[:5]
            ],
        }
        for name, rows in categories.items()
    }


def _regional_fairness(cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_language: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        by_language[case["language"]].append(case)
    return {
        "average_v1_rank_by_language": {language: _average(case["v1_rank"] for case in rows) for language, rows in sorted(by_language.items())},
        "average_v2_rank_by_language": {language: _average(case["v2_rank"] for case in rows) for language, rows in sorted(by_language.items())},
        "median_v1_rank_by_language": {language: _median(case["v1_rank"] for case in rows) for language, rows in sorted(by_language.items())},
        "median_v2_rank_by_language": {language: _median(case["v2_rank"] for case in rows) for language, rows in sorted(by_language.items())},
        "average_rank_delta_by_language": {language: _average(case["rank_delta"] for case in rows) for language, rows in sorted(by_language.items())},
        "top_10_language_distribution_v1": _top_language_distribution(cases, "v1_rank", 10),
        "top_10_language_distribution_v2": _top_language_distribution(cases, "v2_rank", 10),
        "top_20_language_distribution_v1": _top_language_distribution(cases, "v1_rank", 20),
        "top_20_language_distribution_v2": _top_language_distribution(cases, "v2_rank", 20),
        "large_upward_share_by_language": {
            language: _safe_rate(sum(1 for case in rows if (case["rank_delta"] or 0) >= 10), len(rows))
            for language, rows in sorted(by_language.items())
        },
        "large_downward_share_by_language": {
            language: _safe_rate(sum(1 for case in rows if (case["rank_delta"] or 0) <= -10), len(rows))
            for language, rows in sorted(by_language.items())
        },
        "cohort_fallback_rate_by_language": {
            language: _safe_rate(sum(1 for case in rows if case["selected_cohort_level"] != "level_1"), len(rows))
            for language, rows in sorted(by_language.items())
        },
        "average_confidence_by_language": {
            language: _average(case["confidence"] for case in rows)
            for language, rows in sorted(by_language.items())
        },
        "average_quality_component_by_language": {
            language: _average(case["quality"] for case in rows)
            for language, rows in sorted(by_language.items())
        },
        "average_reach_component_by_language": {
            language: _average(case["reach_average"] for case in rows)
            for language, rows in sorted(by_language.items())
        },
    }


def _load_judgments(*, judgment_file: Path | None, shadow_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if judgment_file is None:
        return {}
    valid_movie_ids = {str(row["tmdb_movie_id"]) for row in shadow_rows}
    judgments: dict[str, dict[str, Any]] = {}
    with Path(judgment_file).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("judgment file is missing a header row")
        missing_columns = [column for column in REQUIRED_JUDGMENT_COLUMNS if column not in reader.fieldnames]
        if missing_columns:
            raise ValueError(f"judgment file missing required columns: {', '.join(missing_columns)}")
        seen_pairs: set[tuple[str, str]] = set()
        for row in reader:
            tmdb_movie_id = str(row.get("tmdb_movie_id") or "").strip()
            case_id = str(row.get("evaluation_case_id") or "").strip()
            pair = (case_id, tmdb_movie_id)
            if pair in seen_pairs:
                raise ValueError(f"duplicate judgment row for evaluation_case_id={case_id} tmdb_movie_id={tmdb_movie_id}")
            seen_pairs.add(pair)
            if tmdb_movie_id not in valid_movie_ids:
                raise ValueError(f"judgment references unknown tmdb_movie_id: {tmdb_movie_id}")
            relevance_grade = str(row.get("relevance_grade") or "").strip()
            quality_grade = str(row.get("quality_grade") or "").strip()
            confidence = str(row.get("confidence_in_judgment") or "").strip().upper()
            reviewer_notes = str(row.get("reviewer_notes") or "")
            if relevance_grade not in ALLOWED_GRADE_VALUES:
                raise ValueError(f"invalid relevance_grade: {relevance_grade}")
            if quality_grade not in ALLOWED_GRADE_VALUES:
                raise ValueError(f"invalid quality_grade: {quality_grade}")
            if confidence not in ALLOWED_JUDGMENT_CONFIDENCE:
                raise ValueError(f"invalid confidence_in_judgment: {confidence}")
            judgments[tmdb_movie_id] = {
                "evaluation_case_id": case_id,
                "query_or_context": str(row.get("query_or_context") or "").strip(),
                "tmdb_movie_id": tmdb_movie_id,
                "language": str(row.get("language") or "").strip().casefold(),
                "relevance_grade": int(relevance_grade),
                "quality_grade": int(quality_grade),
                "confidence_in_judgment": confidence,
                "reviewer_notes": reviewer_notes,
            }
    return judgments


def _top_overlap(cases: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    v1 = {case["tmdb_movie_id"] for case in cases if case["v1_rank"] is not None and case["v1_rank"] <= limit}
    v2 = {case["tmdb_movie_id"] for case in cases if case["v2_rank"] is not None and case["v2_rank"] <= limit}
    overlap = sorted(v1 & v2)
    return {
        "count": len(overlap),
        "limit": limit,
        "v1_count": len(v1),
        "v2_count": len(v2),
        "overlap_ids": overlap,
    }


def _spearman(cases: list[dict[str, Any]]) -> float | None:
    paired = [(case["v1_rank"], case["v2_rank"]) for case in cases if case["v1_rank"] is not None and case["v2_rank"] is not None]
    count = len(paired)
    if count < 2:
        return None
    diff_squared = sum((left - right) ** 2 for left, right in paired)
    return round(1 - ((6 * diff_squared) / (count * ((count**2) - 1))), 6)


def _kendall_tau_b(cases: list[dict[str, Any]]) -> float | None:
    paired = [(case["v1_rank"], case["v2_rank"]) for case in cases if case["v1_rank"] is not None and case["v2_rank"] is not None]
    count = len(paired)
    if count < 2:
        return None
    concordant = 0
    discordant = 0
    ties_left = 0
    ties_right = 0
    for index, left in enumerate(paired):
        for right in paired[index + 1 :]:
            left_diff = left[0] - right[0]
            right_diff = left[1] - right[1]
            if left_diff == 0 and right_diff == 0:
                continue
            if left_diff == 0:
                ties_left += 1
                continue
            if right_diff == 0:
                ties_right += 1
                continue
            if left_diff * right_diff > 0:
                concordant += 1
            else:
                discordant += 1
    denominator = math.sqrt((concordant + discordant + ties_left) * (concordant + discordant + ties_right))
    if denominator == 0:
        return None
    return round((concordant - discordant) / denominator, 6)


def _top_language_distribution(cases: list[dict[str, Any]], rank_key: str, limit: int) -> dict[str, int]:
    return dict(
        sorted(
            Counter(case["language"] for case in cases if case[rank_key] is not None and case[rank_key] <= limit).items()
        )
    )


def _manual_review_status(assignment: dict[str, Any]) -> str:
    if assignment.get("review_decision") == "CONFIRMED":
        return "CONFIRMED"
    if assignment.get("review_decision") == "REJECTED":
        return "REJECTED"
    if assignment.get("review_decision") == "NEEDS_FOLLOW_UP":
        return "NEEDS_FOLLOW_UP"
    if assignment.get("review_decision") in ACCEPTED_REVIEW_DECISIONS:
        return "PENDING"
    return "PENDING"


def _confidence_band(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value < 0.50:
        return "low"
    if value < 0.75:
        return "medium"
    return "high"


def _band_from_component(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value <= 0.25:
        return "low"
    if value >= 0.75:
        return "high"
    return "medium"


def _thresholds_for_assignment(*, assignment: dict[str, Any], cohort_record: dict[str, Any] | None, overall_thresholds: dict[str, dict[str, float | None]]) -> dict[str, dict[str, float | None]]:
    if cohort_record is None:
        return overall_thresholds
    statistics = cohort_record.get("signal_statistics", {})
    return {
        "rating": {
            "p25": statistics.get("tmdb_rating_normalized", {}).get("p25"),
            "p75": statistics.get("tmdb_rating_normalized", {}).get("p75"),
        },
        "vote": {
            "p25": statistics.get("tmdb_vote_count_log1p", {}).get("p25"),
            "p75": statistics.get("tmdb_vote_count_log1p", {}).get("p75"),
        },
        "popularity": {
            "p25": statistics.get("tmdb_popularity_log1p", {}).get("p25"),
            "p75": statistics.get("tmdb_popularity_log1p", {}).get("p75"),
        },
    }


def _overall_thresholds(assignments: Any) -> dict[str, dict[str, float | None]]:
    values = {
        "rating": sorted(
            float(row["signal_values"]["tmdb_rating_normalized"]["value"])
            for row in assignments
            if row["signal_values"]["tmdb_rating_normalized"]["value"] is not None
        ),
        "vote": sorted(
            float(row["signal_values"]["tmdb_vote_count_log1p"]["value"])
            for row in assignments
            if row["signal_values"]["tmdb_vote_count_log1p"]["value"] is not None
        ),
        "popularity": sorted(
            float(row["signal_values"]["tmdb_popularity_log1p"]["value"])
            for row in assignments
            if row["signal_values"]["tmdb_popularity_log1p"]["value"] is not None
        ),
    }
    return {
        name: {"p25": _percentile_from_sorted(rows, 25), "p75": _percentile_from_sorted(rows, 75)}
        for name, rows in values.items()
    }


def _group_from_thresholds(value: float | None, thresholds: dict[str, float | None]) -> str:
    if value is None:
        return "unknown"
    low = thresholds.get("p25")
    high = thresholds.get("p75")
    if low is None or high is None:
        return "unknown"
    if value <= low:
        return "low"
    if value >= high:
        return "high"
    return "medium"


def _recompute_shadow_total(row: dict[str, Any]) -> float | None:
    if row["raw_total"] is None:
        return None
    total = 0.0
    for name in SCORED_WEIGHT_COMPONENT_NAMES:
        component_name = {
            "quality": "quality_component",
            "vote_reach": "vote_reach_component",
            "popularity_reach": "popularity_reach_component",
            "confidence": "confidence_component",
        }[name]
        weight = row["active_weights"].get(name)
        value = row.get(component_name)
        if weight is None or value is None:
            continue
        total += weight * value
    return round(total, 6)


def _ndcg(grades: list[int], limit: int) -> float | None:
    if not grades:
        return None
    actual = _dcg(grades[:limit])
    ideal = _dcg(sorted(grades, reverse=True)[:limit])
    if ideal == 0:
        return None
    return round(actual / ideal, 6)


def _dcg(grades: list[int]) -> float:
    return sum(((2**grade) - 1) / math.log2(index + 2) for index, grade in enumerate(grades))


def _precision_at_k(grades: list[int], limit: int) -> float | None:
    if not grades:
        return None
    selected = grades[:limit]
    if not selected:
        return None
    return round(sum(1 for grade in selected if grade >= 2) / len(selected), 6)


def _recall_at_k(grades: list[int], limit: int, *, total_relevant: int) -> float | None:
    if total_relevant <= 0:
        return None
    return round(sum(1 for grade in grades[:limit] if grade >= 2) / total_relevant, 6)


def _mrr(grades: list[int]) -> float | None:
    for index, grade in enumerate(grades, start=1):
        if grade >= 2:
            return round(1.0 / index, 6)
    return 0.0 if grades else None


def _pairwise_preference_accuracy(cases: list[dict[str, Any]], *, rank_key: str) -> float | None:
    comparable = 0
    correct = 0
    for index, left in enumerate(cases):
        for right in cases[index + 1 :]:
            left_grade = left["judgment"]["relevance_grade"]
            right_grade = right["judgment"]["relevance_grade"]
            if left_grade == right_grade:
                continue
            comparable += 1
            expected_better = left if left_grade > right_grade else right
            actual_better = left if (left[rank_key] or 10**9) < (right[rank_key] or 10**9) else right
            if expected_better["tmdb_movie_id"] == actual_better["tmdb_movie_id"]:
                correct += 1
    if comparable == 0:
        return None
    return round(correct / comparable, 6)


def _metric_delta(v1: dict[str, Any], v2: dict[str, Any]) -> dict[str, Any]:
    return {
        key: round(v2[key] - v1[key], 6) if v1.get(key) is not None and v2.get(key) is not None else None
        for key in sorted(v1)
    }


def _summarize_regressions(regressions: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    return {
        "blocking": len(regressions[SEVERITY_BLOCKING]),
        "warning": len(regressions[SEVERITY_WARNING]),
        "informational": len(regressions[SEVERITY_INFORMATIONAL]),
    }


def _deduplicate_regressions(regressions: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    output = {}
    for severity, findings in regressions.items():
        deduped = {}
        for finding in findings:
            key = (
                finding["code"],
                tuple(finding.get("affected_movie_ids", [])),
                json.dumps(finding.get("evidence", {}), sort_keys=True),
            )
            deduped[key] = finding
        output[severity] = sorted(deduped.values(), key=lambda row: (row["code"], row.get("affected_movie_ids", []), json.dumps(row.get("evidence", {}), sort_keys=True)))
    return output


def _add_regression(
    regressions: dict[str, list[dict[str, Any]]],
    *,
    severity: str,
    code: str,
    message: str,
    affected_movie_ids: list[str],
    evidence: dict[str, Any],
) -> None:
    regressions[severity].append(
        {
            "severity": severity,
            "code": code,
            "message": message,
            "affected_movie_ids": sorted(set(affected_movie_ids)),
            "evidence": evidence,
        }
    )


def _average(values: Any) -> float | None:
    filtered = [float(value) for value in values if value is not None]
    if not filtered:
        return None
    return round(sum(filtered) / len(filtered), 6)


def _median(values: Any) -> float | None:
    filtered = sorted(float(value) for value in values if value is not None)
    if not filtered:
        return None
    return round(median(filtered), 6)


def _safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def _percentile_from_sorted(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 6)
    position = (len(values) - 1) * (percentile / 100)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(values[lower], 6)
    fraction = position - lower
    interpolated = values[lower] + (values[upper] - values[lower]) * fraction
    return round(interpolated, 6)


def _round_float(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
