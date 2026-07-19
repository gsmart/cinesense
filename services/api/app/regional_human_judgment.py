from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from app.cine_score_v2 import ShadowScoreWeights
from app.regional_shadow_scoring import run_regional_shadow_scoring

JUDGMENT_SCHEMA_VERSION = "regional-human-ranking-judgment-v1"
DEFAULT_CASES_OUTPUT_ROOT = Path("/tmp/cinesense-regional-judgment-cases")
DEFAULT_REVIEWED_OUTPUT_ROOT = Path("/tmp/cinesense-regional-reviewed-judgments")
DEFAULT_WEIGHT_OUTPUT_ROOT = Path("/tmp/cinesense-regional-weight-evaluation")

DEFAULT_CASE_TYPES = (
    "PAIRWISE_RANKING_COMPARISON",
    "TOP_K_SELECTION_WITHIN_GROUP",
    "UNEXPECTED_MOVEMENT_REVIEW",
    "HIGH_QUALITY_LOW_REACH_REVIEW",
    "HIGH_REACH_LOWER_QUALITY_REVIEW",
    "LARGE_V1_V2_DISAGREEMENT_REVIEW",
    "FALLBACK_LEVEL_REVIEW",
    "CONFIDENCE_BOUNDARY_REVIEW",
    "CROSS_LANGUAGE_BALANCED_DIAGNOSTIC_SAMPLE",
)
DEFAULT_CASES_PER_LANGUAGE = 6
DEFAULT_MAX_TOTAL_CASES = 24

REVIEWER_PREFERENCE_VALUES = ("A_HIGHER", "B_HIGHER", "ROUGHLY_EQUAL", "CANNOT_JUDGE")
REVIEWER_CONFIDENCE_VALUES = ("HIGH", "MEDIUM", "LOW")
REVIEWER_REASON_CODES = (
    "STRONGER_CINEMATIC_QUALITY",
    "BETTER_WITHIN_GENRE",
    "CULTURAL_SIGNIFICANCE",
    "EXECUTION_AND_CRAFT",
    "AUDIENCE_RECEPTION",
    "EVIDENCE_TOO_WEAK",
    "NOT_COMPARABLE",
    "OTHER",
)
REVIEWER_EDITABLE_COLUMNS = ("reviewer_preference", "reviewer_confidence", "reviewer_reason_code", "reviewer_notes")
FORMULA_PREFIXES = ("=", "+", "-", "@")
REVIEWER_CONFIDENCE_WEIGHTS = {
    "HIGH": 1.0,
    "MEDIUM": 0.5,
    "LOW": 0.25,
}
WEIGHT_GRID_VERSION = "cine-score-v2-weight-grid-v1"
WEIGHT_CANDIDATES = (
    ("control", ShadowScoreWeights(quality=0.60, vote_reach=0.20, popularity_reach=0.10, confidence=0.10)),
    ("quality_plus", ShadowScoreWeights(quality=0.65, vote_reach=0.15, popularity_reach=0.10, confidence=0.10)),
    ("vote_plus_popularity_down", ShadowScoreWeights(quality=0.60, vote_reach=0.25, popularity_reach=0.05, confidence=0.10)),
    ("popularity_split", ShadowScoreWeights(quality=0.58, vote_reach=0.17, popularity_reach=0.15, confidence=0.10)),
    ("confidence_plus", ShadowScoreWeights(quality=0.55, vote_reach=0.20, popularity_reach=0.10, confidence=0.15)),
)
STATUS_INSUFFICIENT = "INSUFFICIENT_HUMAN_JUDGMENTS"
STATUS_REVIEW_INCOMPLETE = "HUMAN_JUDGMENT_REVIEW_INCOMPLETE"
STATUS_CONTROL_PREFERRED = "CONTROL_REMAINS_PREFERRED"
STATUS_MORE_REVIEW = "CANDIDATE_REQUIRES_MORE_REVIEW"
STATUS_SHOWS_PROMISE = "CANDIDATE_SHOWS_PROMISE"
STATUS_NO_STABLE_IMPROVEMENT = "NO_STABLE_IMPROVEMENT"
STATUS_BLOCKED = "BLOCKED_BY_REGRESSION"
APPROVAL_STATUS = "HUMAN_EVALUATION_ONLY"


@dataclass(frozen=True)
class JudgmentCaseBuilderConfig:
    cases_per_language: int = DEFAULT_CASES_PER_LANGUAGE
    max_total_cases: int = DEFAULT_MAX_TOTAL_CASES
    case_types: tuple[str, ...] = DEFAULT_CASE_TYPES


def build_regional_judgment_cases(
    *,
    evaluation_dir: Path,
    output_dir: Path | None = None,
    config: JudgmentCaseBuilderConfig | None = None,
) -> dict[str, Any]:
    config = config or JudgmentCaseBuilderConfig()
    context = _load_evaluation_context(Path(evaluation_dir).resolve())
    output_dir = (Path(output_dir).resolve() if output_dir else (DEFAULT_CASES_OUTPUT_ROOT / context["run_id"]).resolve())
    output_dir.mkdir(parents=True, exist_ok=True)

    blinded_rows, mapping_rows = _build_case_rows(context=context, config=config)
    judgment_csv_path = output_dir / "judgment_cases.csv"
    mapping_path = output_dir / "judgment_case_mapping.jsonl"
    manifest_path = output_dir / "judgment_manifest.json"

    _write_csv(judgment_csv_path, blinded_rows)
    _write_jsonl(mapping_path, mapping_rows)

    manifest = {
        "schema_version": JUDGMENT_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "run_id": context["run_id"],
        "score_version": context["score_version"],
        "baseline_version": context["baseline_version"],
        "source_paths": context["source_paths"],
        "source_hashes": context["source_hashes"],
        "configuration": {
            "cases_per_language": config.cases_per_language,
            "max_total_cases": config.max_total_cases,
            "case_types": list(config.case_types),
            "reviewer_blinding": {
                "excluded_fields": ["v1_rank", "v2_rank", "v1_score", "v2_score", "rank_delta", "weight_configuration"],
                "primary_unit": "pairwise_comparison",
            },
        },
        "record_counts": {
            "judgment_cases": len(blinded_rows),
            "languages": len({row["language"] for row in blinded_rows}),
        },
        "case_type_counts": dict(sorted(Counter(row["case_type"] for row in blinded_rows).items())),
        "language_counts": dict(sorted(Counter(row["language"] for row in blinded_rows).items())),
    }
    manifest["output_hashes"] = {
        judgment_csv_path.name: _sha256_path(judgment_csv_path),
        mapping_path.name: _sha256_path(mapping_path),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "output_dir": output_dir,
        "judgment_cases_path": judgment_csv_path,
        "mapping_path": mapping_path,
        "manifest_path": manifest_path,
        "record_count": len(blinded_rows),
        "language_counts": manifest["language_counts"],
        "case_type_counts": manifest["case_type_counts"],
        "output_hashes": {
            judgment_csv_path.name: _sha256_path(judgment_csv_path),
            mapping_path.name: _sha256_path(mapping_path),
            manifest_path.name: _sha256_path(manifest_path),
        },
    }


def import_reviewed_regional_judgments(
    *,
    judgment_dir: Path,
    reviewed_csv_path: Path,
    output_dir: Path | None = None,
    reviewer_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = _load_judgment_case_context(Path(judgment_dir).resolve())
    reviewed_csv_path = Path(reviewed_csv_path).resolve()
    output_dir = (Path(output_dir).resolve() if output_dir else (DEFAULT_REVIEWED_OUTPUT_ROOT / context["run_id"]).resolve())
    output_dir.mkdir(parents=True, exist_ok=True)

    reviewed_rows = _validate_and_normalize_review_csv(
        generated_rows=context["csv_rows"],
        reviewed_csv_path=reviewed_csv_path,
    )

    reviewed_judgments_path = output_dir / "reviewed_judgments.jsonl"
    summary_path = output_dir / "reviewed_judgment_summary.json"
    manifest_path = output_dir / "evaluation_manifest.json"
    _write_jsonl(reviewed_judgments_path, reviewed_rows)

    summary = {
        "schema_version": JUDGMENT_SCHEMA_VERSION,
        "approval_status": APPROVAL_STATUS,
        "activation_eligible": False,
        "run_id": context["run_id"],
        "evaluator_version": JUDGMENT_SCHEMA_VERSION,
        "score_versions_under_comparison": ["cine-score-v1", context["manifest"]["score_version"]],
        "baseline_version": context["manifest"]["baseline_version"],
        "source_judgment_case_file_hash": _sha256_path(context["judgment_cases_path"]),
        "reviewed_csv_hash": _sha256_path(reviewed_csv_path),
        "judgment_manifest_hash": _sha256_path(context["manifest_path"]),
        "evidence_run_identifier": context["run_id"],
        "languages_included": sorted({row["language"] for row in reviewed_rows}),
        "reviewer_decision_counts": dict(sorted(Counter(row["reviewer_preference"] for row in reviewed_rows).items())),
        "reviewer_confidence_counts": dict(sorted(Counter(row["reviewer_confidence"] for row in reviewed_rows).items())),
        "reviewer_reason_counts": dict(sorted(Counter(row["reviewer_reason_code"] for row in reviewed_rows).items())),
        "unresolved_count": sum(1 for row in reviewed_rows if row["reviewer_preference"] == "CANNOT_JUDGE"),
        "cannot_judge_count": sum(1 for row in reviewed_rows if row["reviewer_preference"] == "CANNOT_JUDGE"),
        "reviewed_count": len(reviewed_rows),
        "reviewer_metadata": reviewer_metadata or {},
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    manifest = {
        "schema_version": JUDGMENT_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "approval_status": APPROVAL_STATUS,
        "activation_eligible": False,
        "source_paths": {
            "judgment_dir": str(judgment_dir),
            "reviewed_csv_path": str(reviewed_csv_path),
        },
        "source_hashes": {
            "judgment_cases.csv": _sha256_path(context["judgment_cases_path"]),
            "judgment_case_mapping.jsonl": _sha256_path(context["mapping_path"]),
            "judgment_manifest.json": _sha256_path(context["manifest_path"]),
            reviewed_csv_path.name: _sha256_path(reviewed_csv_path),
        },
        "output_hashes": {
            reviewed_judgments_path.name: _sha256_path(reviewed_judgments_path),
            summary_path.name: _sha256_path(summary_path),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "output_dir": output_dir,
        "reviewed_count": len(reviewed_rows),
        "summary": summary,
        "output_hashes": {
            reviewed_judgments_path.name: _sha256_path(reviewed_judgments_path),
            summary_path.name: _sha256_path(summary_path),
            manifest_path.name: _sha256_path(manifest_path),
        },
    }


def evaluate_regional_weight_configurations(
    *,
    judgment_dir: Path,
    reviewed_dir: Path,
    shadow_dir: Path,
    evaluation_dir: Path,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    judgment_context = _load_judgment_case_context(Path(judgment_dir).resolve())
    reviewed_context = _load_reviewed_context(Path(reviewed_dir).resolve(), judgment_context=judgment_context)
    evaluation_context = _load_evaluation_context(Path(evaluation_dir).resolve())
    shadow_context = _load_shadow_context(Path(shadow_dir).resolve())

    if shadow_context["score_version"] != evaluation_context["score_version"]:
        raise ValueError("score version mismatch between shadow and evaluation artifacts")
    if shadow_context["baseline_hash"] != evaluation_context["source_hashes"]["cohort_baselines.json"]:
        raise ValueError("baseline hash mismatch between shadow and evaluation artifacts")

    output_dir = (Path(output_dir).resolve() if output_dir else (DEFAULT_WEIGHT_OUTPUT_ROOT / evaluation_context["run_id"]).resolve())
    output_dir.mkdir(parents=True, exist_ok=True)
    configs = weight_grid()

    config_results = []
    derived_shadow_hashes = {}
    control_config_id = configs[0]["config_id"]
    for config in configs:
        config_output_dir = output_dir / "_shadow" / config["config_id"]
        shadow_result = run_regional_shadow_scoring(
            run_dir=shadow_context["run_dir"],
            baseline_dir=shadow_context["baseline_dir"],
            output_dir=config_output_dir,
            weights=config["weights"],
        )
        derived_shadow_hashes[config["config_id"]] = shadow_result["output_hashes"]
        config_results.append(
            _evaluate_single_weight_config(
                config=config,
                shadow_result=shadow_result,
                reviewed_rows=reviewed_context["reviewed_rows"],
                mapping_rows=judgment_context["mapping_rows"],
                control_config_id=control_config_id,
            )
        )

    control_result = next(result for result in config_results if result["config_id"] == control_config_id)
    recommendation = _recommend_weight_configuration(config_results=config_results, control_result=control_result)

    summary_path = output_dir / "weight_evaluation_summary.json"
    cases_path = output_dir / "weight_evaluation_cases.jsonl"
    language_path = output_dir / "language_weight_comparison.json"
    recommendation_path = output_dir / "evaluation_recommendation.json"
    manifest_path = output_dir / "evaluation_manifest.json"

    cases_rows = _build_weight_case_rows(config_results=config_results, reviewed_rows=reviewed_context["reviewed_rows"], mapping_rows=judgment_context["mapping_rows"])
    language_comparison = {
        result["config_id"]: result["per_language"]
        for result in config_results
    }
    summary = {
        "schema_version": JUDGMENT_SCHEMA_VERSION,
        "weight_grid_version": WEIGHT_GRID_VERSION,
        "approval_status": APPROVAL_STATUS,
        "activation_eligible": False,
        "run_id": evaluation_context["run_id"],
        "configurations": config_results,
        "control_configuration_id": control_config_id,
        "reviewed_judgment_counts": reviewed_context["summary"]["reviewer_decision_counts"],
        "reviewed_count": reviewed_context["summary"]["reviewed_count"],
        "recommendation_status": recommendation["status"],
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    _write_jsonl(cases_path, cases_rows)
    language_path.write_text(json.dumps(language_comparison, indent=2, sort_keys=True), encoding="utf-8")
    recommendation_path.write_text(json.dumps(recommendation, indent=2, sort_keys=True), encoding="utf-8")
    manifest = {
        "schema_version": JUDGMENT_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "weight_grid_version": WEIGHT_GRID_VERSION,
        "approval_status": APPROVAL_STATUS,
        "activation_eligible": False,
        "source_paths": {
            "judgment_dir": str(judgment_dir),
            "reviewed_dir": str(reviewed_dir),
            "shadow_dir": str(shadow_dir),
            "evaluation_dir": str(evaluation_dir),
        },
        "source_hashes": {
            "judgment_cases.csv": _sha256_path(judgment_context["judgment_cases_path"]),
            "judgment_case_mapping.jsonl": _sha256_path(judgment_context["mapping_path"]),
            "reviewed_judgments.jsonl": _sha256_path(reviewed_context["reviewed_path"]),
            "reviewed_judgment_summary.json": _sha256_path(reviewed_context["summary_path"]),
            "shadow_manifest.json": _sha256_path(shadow_context["manifest_path"]),
            "evaluation_manifest.json": _sha256_path(evaluation_context["manifest_path"]),
        },
        "derived_shadow_hashes": derived_shadow_hashes,
        "output_hashes": {},
    }
    manifest["output_hashes"] = {
        summary_path.name: _sha256_path(summary_path),
        cases_path.name: _sha256_path(cases_path),
        language_path.name: _sha256_path(language_path),
        recommendation_path.name: _sha256_path(recommendation_path),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "output_dir": output_dir,
        "summary": summary,
        "recommendation": recommendation,
        "output_hashes": {
            summary_path.name: _sha256_path(summary_path),
            cases_path.name: _sha256_path(cases_path),
            language_path.name: _sha256_path(language_path),
            recommendation_path.name: _sha256_path(recommendation_path),
            manifest_path.name: _sha256_path(manifest_path),
        },
    }


def weight_grid() -> list[dict[str, Any]]:
    configs = []
    for config_id, weights in WEIGHT_CANDIDATES:
        weights.validate()
        configs.append(
            {
                "config_id": config_id,
                "weights": weights,
                "weights_dict": weights.as_dict(),
            }
        )
    return configs


def _load_evaluation_context(evaluation_dir: Path) -> dict[str, Any]:
    summary_path = evaluation_dir / "evaluation_summary.json"
    cases_path = evaluation_dir / "evaluation_cases.jsonl"
    manifest_path = evaluation_dir / "evaluation_manifest.json"
    for path in (summary_path, cases_path, manifest_path):
        if not path.exists():
            raise ValueError(f"missing evaluation artifact: {path.name}")
    summary = _read_json(summary_path)
    manifest = _read_json(manifest_path)
    cases = _read_jsonl(cases_path)
    return {
        "evaluation_dir": evaluation_dir,
        "summary": summary,
        "manifest": manifest,
        "cases": cases,
        "run_id": summary["source_hashes"].get("run_manifest.json", "")[:12] or Path(manifest["source_paths"]["shadow_dir"]).name,
        "score_version": summary["score_version"],
        "baseline_version": summary["baseline_version"],
        "source_hashes": summary["source_hashes"],
        "source_paths": manifest["source_paths"],
        "manifest_path": manifest_path,
    }


def _load_shadow_context(shadow_dir: Path) -> dict[str, Any]:
    manifest_path = shadow_dir / "shadow_manifest.json"
    comparison_path = shadow_dir / "v1_v2_comparison.json"
    ranking_path = shadow_dir / "shadow_ranking.json"
    summary_path = shadow_dir / "shadow_summary.json"
    if not manifest_path.exists():
        raise ValueError("missing shadow artifact: shadow_manifest.json")
    manifest = _read_json(manifest_path)
    comparison_rows = _read_json(comparison_path)["rows"]
    ranking = _read_json(ranking_path)
    summary = _read_json(summary_path)
    return {
        "manifest": manifest,
        "manifest_path": manifest_path,
        "score_version": manifest["score_version"],
        "baseline_hash": manifest["baseline_hash"],
        "run_dir": Path(manifest["source_paths"]["run_dir"]).resolve(),
        "baseline_dir": Path(manifest["source_paths"]["baseline_dir"]).resolve(),
        "comparison_rows": comparison_rows,
        "ranking": ranking,
        "summary": summary,
    }


def _load_judgment_case_context(judgment_dir: Path) -> dict[str, Any]:
    judgment_cases_path = judgment_dir / "judgment_cases.csv"
    mapping_path = judgment_dir / "judgment_case_mapping.jsonl"
    manifest_path = judgment_dir / "judgment_manifest.json"
    for path in (judgment_cases_path, mapping_path, manifest_path):
        if not path.exists():
            raise ValueError(f"missing judgment artifact: {path.name}")
    with judgment_cases_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        csv_rows = list(reader)
        fieldnames = tuple(reader.fieldnames or ())
    mapping_rows = _read_jsonl(mapping_path)
    manifest = _read_json(manifest_path)
    return {
        "judgment_dir": judgment_dir,
        "judgment_cases_path": judgment_cases_path,
        "mapping_path": mapping_path,
        "manifest_path": manifest_path,
        "csv_rows": csv_rows,
        "mapping_rows": mapping_rows,
        "manifest": manifest,
        "fieldnames": fieldnames,
        "run_id": manifest["run_id"],
    }


def _load_reviewed_context(reviewed_dir: Path, *, judgment_context: dict[str, Any]) -> dict[str, Any]:
    reviewed_path = reviewed_dir / "reviewed_judgments.jsonl"
    summary_path = reviewed_dir / "reviewed_judgment_summary.json"
    if not reviewed_path.exists() or not summary_path.exists():
        raise ValueError("missing reviewed judgment artifacts")
    summary = _read_json(summary_path)
    if summary["source_judgment_case_file_hash"] != _sha256_path(judgment_context["judgment_cases_path"]):
        raise ValueError("reviewed judgments do not match the supplied judgment case file")
    return {
        "reviewed_path": reviewed_path,
        "summary_path": summary_path,
        "reviewed_rows": _read_jsonl(reviewed_path),
        "summary": summary,
    }


def _build_case_rows(*, context: dict[str, Any], config: JudgmentCaseBuilderConfig) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    cases = context["cases"]
    by_language: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        by_language[case["language"]].append(case)
    blinded_rows: list[dict[str, str]] = []
    mapping_rows: list[dict[str, Any]] = []
    used_pairs: set[tuple[str, str, str]] = set()
    global_index = 1
    for language in sorted(by_language):
        language_rows = sorted(
            by_language[language],
            key=lambda row: (
                row["v2_rank"] if row["v2_rank"] is not None else 10**9,
                row["tmdb_movie_id"],
            ),
        )
        generated_for_language = 0
        for case_type in config.case_types:
            if generated_for_language >= config.cases_per_language or len(blinded_rows) >= config.max_total_cases:
                break
            pair = _select_pair_for_case_type(language_rows, case_type=case_type)
            if pair is None:
                continue
            left, right = pair
            pair_key = (case_type, left["tmdb_movie_id"], right["tmdb_movie_id"])
            if pair_key in used_pairs:
                continue
            used_pairs.add(pair_key)
            case_id = f"{language}-{global_index:03d}"
            global_index += 1
            blinded_row, mapping_row = _build_blinded_pair_row(case_id=case_id, case_type=case_type, left=left, right=right)
            blinded_rows.append(blinded_row)
            mapping_rows.append(mapping_row)
            generated_for_language += 1
        if len(blinded_rows) >= config.max_total_cases:
            break
    return blinded_rows, mapping_rows


def _select_pair_for_case_type(rows: list[dict[str, Any]], *, case_type: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if len(rows) < 2:
        return None
    if case_type == "PAIRWISE_RANKING_COMPARISON":
        selected = sorted(rows, key=lambda row: (-abs(row["rank_delta"] or 0), row["tmdb_movie_id"]))[:2]
        return _ordered_pair(selected[0], selected[1]) if len(selected) == 2 else None
    if case_type == "TOP_K_SELECTION_WITHIN_GROUP":
        top = [row for row in rows if row["v2_rank"] is not None and row["v2_rank"] <= 6]
        return _ordered_pair(top[-2], top[-1]) if len(top) >= 2 else _adjacent_pair(rows)
    if case_type == "UNEXPECTED_MOVEMENT_REVIEW":
        selected = [row for row in rows if "high_rating_down_unexpected" in json.dumps(row).lower() or "low_rating_up_unexpected" in json.dumps(row).lower()]
        if len(selected) >= 2:
            return _ordered_pair(selected[0], selected[1])
        selected = sorted(rows, key=lambda row: (row["quality_group"] != "high", -(abs(row["rank_delta"] or 0)), row["tmdb_movie_id"]))
        return _ordered_pair(selected[0], selected[1])
    if case_type == "HIGH_QUALITY_LOW_REACH_REVIEW":
        selected = [row for row in rows if row["quality_group"] == "high" and row["reach_group"] == "low"]
        if len(selected) >= 2:
            return _ordered_pair(selected[0], selected[1])
        return _contrast_pair(rows, left_filter=lambda row: row["quality_group"] == "high", right_filter=lambda row: row["reach_group"] == "high")
    if case_type == "HIGH_REACH_LOWER_QUALITY_REVIEW":
        return _contrast_pair(rows, left_filter=lambda row: row["reach_group"] == "high", right_filter=lambda row: row["quality_group"] == "high")
    if case_type == "LARGE_V1_V2_DISAGREEMENT_REVIEW":
        ordered = sorted(rows, key=lambda row: (-abs(row["rank_delta"] or 0), row["tmdb_movie_id"]))
        return _ordered_pair(ordered[0], ordered[1])
    if case_type == "FALLBACK_LEVEL_REVIEW":
        return _contrast_pair(rows, left_filter=lambda row: row["selected_cohort_level"] != "level_1", right_filter=lambda row: row["selected_cohort_level"] == "level_1")
    if case_type == "CONFIDENCE_BOUNDARY_REVIEW":
        ordered = sorted(rows, key=lambda row: (row["confidence"] is None, row["confidence"] if row["confidence"] is not None else 10**9, row["tmdb_movie_id"]))
        return _ordered_pair(ordered[0], ordered[-1]) if len(ordered) >= 2 else None
    if case_type == "CROSS_LANGUAGE_BALANCED_DIAGNOSTIC_SAMPLE":
        midpoint = len(rows) // 2
        if midpoint <= 0:
            return _adjacent_pair(rows)
        return _ordered_pair(rows[midpoint - 1], rows[midpoint])
    return None


def _ordered_pair(left: dict[str, Any], right: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if _pair_sort_key(left) <= _pair_sort_key(right):
        return left, right
    return right, left


def _pair_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row["v2_rank"] if row["v2_rank"] is not None else 10**9,
        row["v1_rank"] if row["v1_rank"] is not None else 10**9,
        row["tmdb_movie_id"],
    )


def _adjacent_pair(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    return _ordered_pair(rows[0], rows[1])


def _contrast_pair(
    rows: list[dict[str, Any]],
    *,
    left_filter: Any,
    right_filter: Any,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    left = next((row for row in rows if left_filter(row)), None)
    right = next((row for row in rows if row["tmdb_movie_id"] != (left or {}).get("tmdb_movie_id") and right_filter(row)), None)
    if left is None or right is None:
        return None
    return _ordered_pair(left, right)


def _build_blinded_pair_row(*, case_id: str, case_type: str, left: dict[str, Any], right: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any]]:
    blinded = {
        "judgment_case_id": case_id,
        "case_type": case_type,
        "language": _safe_csv_cell(left["language"]),
        "movie_a_tmdb_id": left["tmdb_movie_id"],
        "movie_b_tmdb_id": right["tmdb_movie_id"],
        "movie_a_title": _safe_csv_cell(str(left["title"] or "")),
        "movie_b_title": _safe_csv_cell(str(right["title"] or "")),
        "movie_a_release_year": _stringify(left["release_year"]),
        "movie_b_release_year": _stringify(right["release_year"]),
        "movie_a_primary_genre": _safe_csv_cell(str(left.get("primary_genre") or "")),
        "movie_b_primary_genre": _safe_csv_cell(str(right.get("primary_genre") or "")),
        "movie_a_tmdb_rating": _stringify(left.get("v1_score")),
        "movie_b_tmdb_rating": _stringify(right.get("v1_score")),
        "movie_a_vote_count": _stringify(left.get("vote_group")),
        "movie_b_vote_count": _stringify(right.get("vote_group")),
        "movie_a_popularity": _stringify(left.get("popularity_group")),
        "movie_b_popularity": _stringify(right.get("popularity_group")),
        "movie_a_cohort_level": _safe_csv_cell(str(left.get("selected_cohort_level") or "")),
        "movie_b_cohort_level": _safe_csv_cell(str(right.get("selected_cohort_level") or "")),
        "movie_a_identity_status": _safe_csv_cell(str(left.get("entity_status") or "")),
        "movie_b_identity_status": _safe_csv_cell(str(right.get("entity_status") or "")),
        "evidence_warnings": _safe_csv_cell("|".join(sorted(set(left["warnings"] + right["warnings"])))),
        "reviewer_preference": "",
        "reviewer_confidence": "",
        "reviewer_reason_code": "",
        "reviewer_notes": "",
    }
    mapping = {
        "judgment_case_id": case_id,
        "case_type": case_type,
        "language": left["language"],
        "movie_a_tmdb_id": left["tmdb_movie_id"],
        "movie_b_tmdb_id": right["tmdb_movie_id"],
        "movie_a_v1_rank": left["v1_rank"],
        "movie_b_v1_rank": right["v1_rank"],
        "movie_a_v2_rank": left["v2_rank"],
        "movie_b_v2_rank": right["v2_rank"],
        "movie_a_v1_score": left["v1_score"],
        "movie_b_v1_score": right["v1_score"],
        "movie_a_v2_score": left["v2_score"],
        "movie_b_v2_score": right["v2_score"],
        "movie_a_rank_delta": left["rank_delta"],
        "movie_b_rank_delta": right["rank_delta"],
        "movie_a_hidden": left,
        "movie_b_hidden": right,
        "reviewer_visible_row": blinded,
    }
    return blinded, mapping


IMMUTABLE_FIELD_SCHEMA = {
    "judgment_case_id": "exact_identifier",
    "case_type": "exact_text",
    "language": "exact_text",
    "movie_a_tmdb_id": "exact_identifier",
    "movie_b_tmdb_id": "exact_identifier",
    "movie_a_title": "normalized_text",
    "movie_b_title": "normalized_text",
    "movie_a_release_year": "nullable_integer",
    "movie_b_release_year": "nullable_integer",
    "movie_a_primary_genre": "normalized_text",
    "movie_b_primary_genre": "normalized_text",
    "movie_a_tmdb_rating": "nullable_decimal",
    "movie_b_tmdb_rating": "nullable_decimal",
    "movie_a_vote_count": "exact_text",
    "movie_b_vote_count": "exact_text",
    "movie_a_popularity": "exact_text",
    "movie_b_popularity": "exact_text",
    "movie_a_cohort_level": "exact_text",
    "movie_b_cohort_level": "exact_text",
    "movie_a_identity_status": "exact_text",
    "movie_b_identity_status": "exact_text",
    "evidence_warnings": "structured_serialized_value",
}


def _unescape_csv_cell(val: str) -> str:
    if val.startswith("'") and len(val) > 1 and val[1] in FORMULA_PREFIXES:
        return val[1:]
    return val


def parse_nullable_int(val: str) -> int | None:
    val_stripped = val.strip()
    if not val_stripped:
        return None
    if "," in val_stripped:
        raise ValueError(f"Comma-formatted numbers are not allowed: {val!r}")
    if "e" in val_stripped.lower():
        raise ValueError(f"Scientific notation is not allowed: {val!r}")
    if val_stripped.lower() in ("true", "false"):
        raise ValueError(f"Boolean values are not allowed: {val!r}")
    try:
        f = float(val_stripped)
    except ValueError:
        raise ValueError(f"Invalid integer: {val!r}")
    if not math.isfinite(f):
        raise ValueError(f"Infinite/NaN is not allowed: {val!r}")
    if f != int(f):
        raise ValueError(f"Not a valid integer: {val!r}")
    return int(f)


def parse_nullable_decimal(val: str) -> float | None:
    val_stripped = val.strip()
    if not val_stripped:
        return None
    if "," in val_stripped:
        raise ValueError(f"Comma-formatted numbers are not allowed: {val!r}")
    if "e" in val_stripped.lower():
        raise ValueError(f"Scientific notation is not allowed: {val!r}")
    if val_stripped.lower() in ("true", "false"):
        raise ValueError(f"Boolean values are not allowed: {val!r}")
    try:
        f = float(val_stripped)
    except ValueError:
        raise ValueError(f"Invalid decimal: {val!r}")
    if not math.isfinite(f):
        raise ValueError(f"Infinite/NaN is not allowed: {val!r}")
    return f


def clean_reviewer_note(val: str) -> str:
    if val.startswith("'") and len(val) > 1 and val[1] in FORMULA_PREFIXES:
        return val[1:]
    if val.startswith("=") or val.startswith("@"):
        raise ValueError("Formula-like notes must be escaped with a leading apostrophe.")
    if val.startswith("+") or val.startswith("-"):
        remaining = val[1:].lstrip()
        if not remaining:
            return val
        if remaining[0].isdigit() or remaining[0] in ("(", "$", "=", "+", "-", "@"):
            raise ValueError("Formula-like notes must be escaped with a leading apostrophe.")
    return val


def _compare_immutable_field(case_id: str, key: str, value: str, expected: str) -> None:
    field_type = IMMUTABLE_FIELD_SCHEMA.get(key)
    if not field_type:
        return

    val_unescaped = _unescape_csv_cell(value)
    exp_unescaped = _unescape_csv_cell(expected)

    if field_type == "exact_identifier":
        if val_unescaped != exp_unescaped:
            raise ValueError(f"immutable column mismatch for {case_id}: {key}")

    elif field_type == "exact_text":
        if val_unescaped != exp_unescaped:
            raise ValueError(f"immutable column mismatch for {case_id}: {key}")

    elif field_type == "normalized_text":
        if val_unescaped.strip() != exp_unescaped.strip():
            raise ValueError(f"immutable column mismatch for {case_id}: {key}")

    elif field_type == "nullable_integer":
        try:
            val_int = parse_nullable_int(val_unescaped)
            exp_int = parse_nullable_int(exp_unescaped)
        except ValueError as exc:
            raise ValueError(f"immutable column mismatch for {case_id}: {key} (invalid integer format: {exc})")
        if val_int != exp_int:
            raise ValueError(f"immutable column mismatch for {case_id}: {key}")

    elif field_type == "nullable_decimal":
        try:
            val_dec = parse_nullable_decimal(val_unescaped)
            exp_dec = parse_nullable_decimal(exp_unescaped)
        except ValueError as exc:
            raise ValueError(f"immutable column mismatch for {case_id}: {key} (invalid decimal format: {exc})")
        if val_dec is None and exp_dec is None:
            pass
        elif val_dec is None or exp_dec is None:
            raise ValueError(f"immutable column mismatch for {case_id}: {key}")
        elif not math.isclose(val_dec, exp_dec, abs_tol=1e-9):
            raise ValueError(f"immutable column mismatch for {case_id}: {key}")

    elif field_type == "structured_serialized_value":
        w_val = sorted([w.strip() for w in val_unescaped.split("|") if w.strip()])
        w_exp = sorted([w.strip() for w in exp_unescaped.split("|") if w.strip()])
        if w_val != w_exp:
            raise ValueError(f"immutable column mismatch for {case_id}: {key}")


def _validate_and_normalize_review_csv(*, generated_rows: list[dict[str, str]], reviewed_csv_path: Path) -> list[dict[str, Any]]:
    generated_by_id = {row["judgment_case_id"]: row for row in generated_rows}

    # Pre-parse duplicate column header check
    with reviewed_csv_path.open("r", encoding="utf-8") as raw_handle:
        raw_reader = csv.reader(raw_handle)
        header = next(raw_reader, None)
        if not header:
            raise ValueError("reviewed CSV is empty or missing a header row")
        seen_cols = set()
        for col in header:
            if not col:
                continue
            if col in seen_cols:
                raise ValueError(f"duplicate column detected in CSV header: {col}")
            seen_cols.add(col)

    with reviewed_csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("reviewed CSV is missing a header row")
        missing_columns = [column for column in generated_rows[0] if column not in reader.fieldnames]
        if missing_columns:
            raise ValueError(f"reviewed CSV missing required columns: {', '.join(missing_columns)}")
        seen_ids: set[str] = set()
        normalized_rows = []
        for row in reader:
            case_id = str(row.get("judgment_case_id") or "").strip()
            if case_id in seen_ids:
                raise ValueError(f"duplicate judgment_case_id: {case_id}")
            seen_ids.add(case_id)
            if case_id not in generated_by_id:
                raise ValueError(f"unknown judgment_case_id: {case_id}")
            generated = generated_by_id[case_id]
            for key, expected in generated.items():
                value = str(row.get(key) or "")
                if key in REVIEWER_EDITABLE_COLUMNS:
                    continue
                _compare_immutable_field(case_id, key, value, expected)
            preference = str(row.get("reviewer_preference") or "").strip()
            confidence = str(row.get("reviewer_confidence") or "").strip()
            reason_code = str(row.get("reviewer_reason_code") or "").strip()
            notes = str(row.get("reviewer_notes") or "")
            if preference not in REVIEWER_PREFERENCE_VALUES:
                raise ValueError(f"invalid reviewer_preference for {case_id}: {preference}")
            if confidence not in REVIEWER_CONFIDENCE_VALUES:
                raise ValueError(f"invalid reviewer_confidence for {case_id}: {confidence}")
            if reason_code not in REVIEWER_REASON_CODES:
                raise ValueError(f"invalid reviewer_reason_code for {case_id}: {reason_code}")

            try:
                cleaned_notes = clean_reviewer_note(notes)
            except ValueError as exc:
                raise ValueError(f"formula-like content rejected for {case_id}: reviewer_notes (reason: {exc})")

            for editable_key, editable_value in {
                "reviewer_preference": preference,
                "reviewer_confidence": confidence,
                "reviewer_reason_code": reason_code,
            }.items():
                if _is_formula_like(editable_value):
                    raise ValueError(f"formula-like content rejected for {case_id}: {editable_key}")
            normalized_rows.append(
                {
                    "judgment_case_id": case_id,
                    "case_type": generated["case_type"],
                    "language": generated["language"],
                    "movie_a_tmdb_id": generated["movie_a_tmdb_id"],
                    "movie_b_tmdb_id": generated["movie_b_tmdb_id"],
                    "reviewer_preference": preference,
                    "reviewer_confidence": confidence,
                    "reviewer_reason_code": reason_code,
                    "reviewer_notes": cleaned_notes,
                }
            )
    expected_ids = sorted(generated_by_id)
    if sorted(seen_ids) != expected_ids:
        missing = sorted(set(expected_ids) - set(seen_ids))
        raise ValueError(f"missing reviewed judgment_case_id values: {', '.join(missing)}")
    normalized_rows.sort(key=lambda row: row["judgment_case_id"])
    return normalized_rows


def _evaluate_single_weight_config(
    *,
    config: dict[str, Any],
    shadow_result: dict[str, Any],
    reviewed_rows: list[dict[str, Any]],
    mapping_rows: list[dict[str, Any]],
    control_config_id: str,
) -> dict[str, Any]:
    ranks = {
        row["tmdb_movie_id"]: row["rank"]
        for row in shadow_result["ranking"]["overall"]
    }
    scores_by_id = {
        row["tmdb_movie_id"]: row["display_total"]
        for row in shadow_result["shadow_rows"]
    }
    v1_ranks = {
        row["tmdb_movie_id"]: row["v1_rank"]
        for row in shadow_result["comparison_rows"]
    }
    judgments_by_id = {row["judgment_case_id"]: row for row in reviewed_rows}
    mapping_by_id = {row["judgment_case_id"]: row for row in mapping_rows}
    pairwise_results = []
    per_language_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    per_case_type_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case_id, mapping in sorted(mapping_by_id.items()):
        judgment = judgments_by_id[case_id]
        predicted = _predict_pairwise_preference(
            movie_a_tmdb_id=mapping["movie_a_tmdb_id"],
            movie_b_tmdb_id=mapping["movie_b_tmdb_id"],
            scores_by_id=scores_by_id,
            ranks_by_id=ranks,
        )
        agreement = _pairwise_agreement(judgment["reviewer_preference"], predicted)
        row = {
            "judgment_case_id": case_id,
            "case_type": mapping["case_type"],
            "language": mapping["language"],
            "reviewer_preference": judgment["reviewer_preference"],
            "reviewer_confidence": judgment["reviewer_confidence"],
            "predicted_preference": predicted,
            "agreement": agreement,
            "weight": REVIEWER_CONFIDENCE_WEIGHTS[judgment["reviewer_confidence"]],
        }
        pairwise_results.append(row)
        per_language_buckets[mapping["language"]].append(row)
        per_case_type_buckets[mapping["case_type"]].append(row)

    overall = _pairwise_metric_summary(pairwise_results)
    per_language = {language: _pairwise_metric_summary(rows) for language, rows in sorted(per_language_buckets.items())}
    per_case_type = {case_type: _pairwise_metric_summary(rows) for case_type, rows in sorted(per_case_type_buckets.items())}
    fallback_diagnostics = dict(sorted(Counter(row["cohort_level"] for row in shadow_result["shadow_rows"]).items()))
    missing_data = {
        "unscorable_count": sum(1 for row in shadow_result["shadow_rows"] if row["display_total"] is None),
        "missing_quality_count": sum(1 for row in shadow_result["shadow_rows"] if row["quality_component"] is None),
        "missing_reach_count": sum(
            1
            for row in shadow_result["shadow_rows"]
            if row["vote_reach_component"] is None and row["popularity_reach_component"] is None
        ),
    }
    v1_rank_pairs = [(row["v1_rank"], ranks[row["tmdb_movie_id"]]) for row in shadow_result["comparison_rows"]]
    average_movement, maximum_movement = _rank_movement(v1_rank_pairs)
    regression_findings = []
    if missing_data["unscorable_count"] > 0:
        regression_findings.append("UNSCORABLE_ROWS_PRESENT")
    if not math.isclose(sum(config["weights_dict"].values()), 1.0, abs_tol=1e-9):
        regression_findings.append("INVALID_WEIGHT_SUM")
    status = _candidate_status(
        config_id=config["config_id"],
        overall=overall,
        per_language=per_language,
        regression_findings=regression_findings,
        control_config_id=control_config_id,
    )
    return {
        "config_id": config["config_id"],
        "weights": config["weights_dict"],
        "overall": overall,
        "per_language": per_language,
        "per_case_type": per_case_type,
        "high_confidence_agreement": _confidence_band_metric(pairwise_results, "HIGH"),
        "medium_confidence_agreement": _confidence_band_metric(pairwise_results, "MEDIUM"),
        "low_confidence_agreement": _confidence_band_metric(pairwise_results, "LOW"),
        "rank_correlation_with_v1": _spearman_pairs(v1_rank_pairs),
        "average_rank_movement_from_v1": average_movement,
        "maximum_rank_movement_from_v1": maximum_movement,
        "fallback_level_diagnostics": fallback_diagnostics,
        "missing_data_diagnostics": missing_data,
        "regression_findings": regression_findings,
        "status": status,
        "pairwise_results": pairwise_results,
    }


def _recommend_weight_configuration(*, config_results: list[dict[str, Any]], control_result: dict[str, Any]) -> dict[str, Any]:
    reviewed_count = control_result["overall"]["reviewed_count"]
    if reviewed_count <= 0:
        return {
            "status": STATUS_REVIEW_INCOMPLETE,
            "recommended_config_id": control_result["config_id"],
            "reason": "no reviewed judgments available",
            "activation_eligible": False,
            "approval_status": APPROVAL_STATUS,
        }
    if reviewed_count < 12:
        return {
            "status": STATUS_INSUFFICIENT,
            "recommended_config_id": control_result["config_id"],
            "reason": "fewer than 12 reviewed judgments",
            "activation_eligible": False,
            "approval_status": APPROVAL_STATUS,
        }
    candidates = [result for result in config_results if result["config_id"] != control_result["config_id"]]
    best = max(candidates, key=lambda row: (row["overall"]["agreement_rate"] or -1.0, row["config_id"]), default=None)
    if best is None:
        return {
            "status": STATUS_CONTROL_PREFERRED,
            "recommended_config_id": control_result["config_id"],
            "reason": "no candidate configurations were evaluated",
            "activation_eligible": False,
            "approval_status": APPROVAL_STATUS,
        }
    if best["regression_findings"]:
        return {
            "status": STATUS_BLOCKED,
            "recommended_config_id": control_result["config_id"],
            "reason": "candidate regression findings present",
            "activation_eligible": False,
            "approval_status": APPROVAL_STATUS,
        }
    control_rate = control_result["overall"]["agreement_rate"] or 0.0
    best_rate = best["overall"]["agreement_rate"] or 0.0
    degraded_language = any(
        (best["per_language"].get(language, {}).get("agreement_rate") or 0.0)
        < (control_result["per_language"].get(language, {}).get("agreement_rate") or 0.0) - 0.05
        for language in control_result["per_language"]
    )
    if best_rate <= control_rate:
        return {
            "status": STATUS_CONTROL_PREFERRED,
            "recommended_config_id": control_result["config_id"],
            "reason": "no candidate exceeded control agreement",
            "activation_eligible": False,
            "approval_status": APPROVAL_STATUS,
        }
    if degraded_language:
        return {
            "status": STATUS_NO_STABLE_IMPROVEMENT,
            "recommended_config_id": control_result["config_id"],
            "reason": "candidate degrades at least one language materially",
            "activation_eligible": False,
            "approval_status": APPROVAL_STATUS,
        }
    if reviewed_count < 24:
        return {
            "status": STATUS_MORE_REVIEW,
            "recommended_config_id": best["config_id"],
            "reason": "candidate improves agreement but review coverage remains narrow",
            "activation_eligible": False,
            "approval_status": APPROVAL_STATUS,
        }
    return {
        "status": STATUS_SHOWS_PROMISE,
        "recommended_config_id": best["config_id"],
        "reason": "candidate improves agreement without language degradation",
        "activation_eligible": False,
        "approval_status": APPROVAL_STATUS,
    }


def _build_weight_case_rows(
    *,
    config_results: list[dict[str, Any]],
    reviewed_rows: list[dict[str, Any]],
    mapping_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    mapping_by_id = {row["judgment_case_id"]: row for row in mapping_rows}
    for result in config_results:
        per_case = {row["judgment_case_id"]: row for row in result["pairwise_results"]}
        for judgment in reviewed_rows:
            case_id = judgment["judgment_case_id"]
            mapping = mapping_by_id[case_id]
            pair_result = per_case[case_id]
            rows.append(
                {
                    "config_id": result["config_id"],
                    "judgment_case_id": case_id,
                    "case_type": mapping["case_type"],
                    "language": mapping["language"],
                    "reviewer_preference": judgment["reviewer_preference"],
                    "reviewer_confidence": judgment["reviewer_confidence"],
                    "predicted_preference": pair_result["predicted_preference"],
                    "agreement": pair_result["agreement"],
                }
            )
    rows.sort(key=lambda row: (row["config_id"], row["judgment_case_id"]))
    return rows


def _predict_pairwise_preference(
    *,
    movie_a_tmdb_id: str,
    movie_b_tmdb_id: str,
    scores_by_id: dict[str, float | None],
    ranks_by_id: dict[str, int],
) -> str:
    score_a = scores_by_id.get(movie_a_tmdb_id)
    score_b = scores_by_id.get(movie_b_tmdb_id)
    if score_a is None and score_b is None:
        return "ROUGHLY_EQUAL"
    if score_a is None:
        return "B_HIGHER"
    if score_b is None:
        return "A_HIGHER"
    if math.isclose(score_a, score_b, abs_tol=1e-9):
        return "ROUGHLY_EQUAL"
    return "A_HIGHER" if ranks_by_id[movie_a_tmdb_id] < ranks_by_id[movie_b_tmdb_id] else "B_HIGHER"


def _pairwise_agreement(reviewer_preference: str, predicted_preference: str) -> str:
    if reviewer_preference == "CANNOT_JUDGE":
        return "CANNOT_JUDGE"
    if reviewer_preference == predicted_preference:
        return "AGREE"
    if reviewer_preference == "ROUGHLY_EQUAL" and predicted_preference == "ROUGHLY_EQUAL":
        return "AGREE"
    return "DISAGREE"


def _pairwise_metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    comparable = [row for row in rows if row["agreement"] != "CANNOT_JUDGE"]
    weighted_total = sum(row["weight"] for row in comparable)
    weighted_agree = sum(row["weight"] for row in comparable if row["agreement"] == "AGREE")
    return {
        "reviewed_count": len(rows),
        "comparable_count": len(comparable),
        "agreement_rate": _safe_rate(sum(1 for row in comparable if row["agreement"] == "AGREE"), len(comparable)),
        "disagreement_rate": _safe_rate(sum(1 for row in comparable if row["agreement"] == "DISAGREE"), len(comparable)),
        "tie_handling_rate": _safe_rate(sum(1 for row in rows if row["reviewer_preference"] == "ROUGHLY_EQUAL"), len(rows)),
        "cannot_judge_rate": _safe_rate(sum(1 for row in rows if row["reviewer_preference"] == "CANNOT_JUDGE"), len(rows)),
        "confidence_weighted_agreement": round(weighted_agree / weighted_total, 6) if weighted_total else None,
    }


def _confidence_band_metric(rows: list[dict[str, Any]], confidence: str) -> float | None:
    filtered = [row for row in rows if row["reviewer_confidence"] == confidence and row["agreement"] != "CANNOT_JUDGE"]
    return _safe_rate(sum(1 for row in filtered if row["agreement"] == "AGREE"), len(filtered))


def _candidate_status(
    *,
    config_id: str,
    overall: dict[str, Any],
    per_language: dict[str, Any],
    regression_findings: list[str],
    control_config_id: str,
) -> str:
    if config_id == control_config_id:
        return STATUS_CONTROL_PREFERRED
    if regression_findings:
        return STATUS_BLOCKED
    if overall["reviewed_count"] < 12:
        return STATUS_INSUFFICIENT
    if any(metrics["reviewed_count"] < 3 for metrics in per_language.values()):
        return STATUS_MORE_REVIEW
    return STATUS_SHOWS_PROMISE if (overall["agreement_rate"] or 0.0) > 0 else STATUS_REVIEW_INCOMPLETE


def _rank_movement(pairs: list[tuple[int | None, int | None]]) -> tuple[float | None, int | None]:
    movements = [abs(left - right) for left, right in pairs if left is not None and right is not None]
    if not movements:
        return None, None
    return round(sum(movements) / len(movements), 6), max(movements)


def _spearman_pairs(pairs: list[tuple[int | None, int | None]]) -> float | None:
    filtered = [(left, right) for left, right in pairs if left is not None and right is not None]
    count = len(filtered)
    if count < 2:
        return None
    diff_squared = sum((left - right) ** 2 for left, right in filtered)
    return round(1 - ((6 * diff_squared) / (count * ((count**2) - 1))), 6)


def _safe_csv_cell(value: str) -> str:
    if value and value[0] in FORMULA_PREFIXES:
        return f"'{value}"
    return value


def _is_formula_like(value: str) -> bool:
    trimmed = value.lstrip()
    return bool(trimmed) and trimmed[0] in FORMULA_PREFIXES


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


def _safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
