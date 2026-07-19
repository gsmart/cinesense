from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Any

from app.regional_evidence_validation import (
    ACCEPTED_REVIEW_DECISIONS,
    BLOCKED_BY_ENTITY_RESOLUTION_QUALITY,
    BLOCKED_BY_LOW_COVERAGE,
    EXACT_MATCH_WITH_WARNINGS,
    SOURCE_ERROR,
    VALIDATED_EXACT_MATCH,
)

BASELINE_SCHEMA_VERSION = "regional-cohort-baseline-v1"
DEFAULT_OUTPUT_ROOT = Path("/tmp/cinesense-regional-baselines")
DEFAULT_LEVEL_THRESHOLDS = {
    "level_1": 10,
    "level_2": 15,
    "level_3": 30,
    "level_4": 60,
}
DEFAULT_ERA_BUCKETS = (
    ("pre_1980", None, 1979),
    ("1980_1999", 1980, 1999),
    ("2000_2009", 2000, 2009),
    ("2010_2019", 2010, 2019),
    ("2020_present", 2020, None),
)
SUPPORTED_LANGUAGES = {"mr", "ml", "ta", "te", "kn", "hi", "bn", "en", "gu"}
READINESS_READY = "READY_FOR_BASELINE_EXPERIMENTS"
READINESS_LIMITED = "READY_WITH_LIMITATIONS"
READINESS_INSUFFICIENT = "INSUFFICIENT_SAMPLE"
READINESS_ENTITY_BLOCKED = "BLOCKED_BY_ENTITY_QUALITY"
READINESS_SOURCE_BLOCKED = "BLOCKED_BY_SOURCE_FAILURE"
PHASE_PROCEED = "PROCEED_TO_SHADOW_SCORE_DESIGN"
PHASE_LIMITED = "PROCEED_WITH_LIMITED_COHORTS"
PHASE_REVIEW = "COMPLETE_MANUAL_REVIEW_FIRST"
PHASE_EXPAND = "EXPAND_SAMPLE_FIRST"
PHASE_BLOCKED = "BLOCKED_BY_DATA_QUALITY"
UNKNOWN_GENRE = "unknown_genre"
UNKNOWN_YEAR = "unknown_year"
GLOBAL_COHORT_KEY = "global=regional_sample"
COHORT_LEVELS = (
    ("level_1", "language_era_genre"),
    ("level_2", "language_era"),
    ("level_3", "language"),
    ("level_4", "global"),
)
ENTITY_STATUS_ORDER = (
    VALIDATED_EXACT_MATCH,
    EXACT_MATCH_WITH_WARNINGS,
    "AMBIGUOUS_REVIEW_REQUIRED",
    "NO_MATCH",
    SOURCE_ERROR,
    "UNVALIDATED",
)
SIGNAL_ORDER = (
    "tmdb_rating",
    "tmdb_rating_normalized",
    "tmdb_vote_count",
    "tmdb_vote_count_log1p",
    "tmdb_popularity",
    "tmdb_popularity_log1p",
)


@dataclass(frozen=True)
class CohortBaselineConfig:
    output_root: Path = DEFAULT_OUTPUT_ROOT
    level_thresholds: dict[str, int] | None = None
    era_buckets: tuple[tuple[str, int | None, int | None], ...] = DEFAULT_ERA_BUCKETS

    def threshold_for(self, level: str) -> int:
        thresholds = self.level_thresholds or DEFAULT_LEVEL_THRESHOLDS
        return thresholds[level]


@dataclass(frozen=True)
class SignalValue:
    value: float
    exclusion_reason: str | None = None


def build_regional_cohort_baselines(
    *,
    run_dir: Path,
    output_dir: Path | None = None,
    review_file: Path | None = None,
    config: CohortBaselineConfig | None = None,
) -> dict[str, Any]:
    config = config or CohortBaselineConfig()
    run_dir = Path(run_dir).resolve()
    output_dir = (output_dir or (config.output_root / run_dir.name)).resolve()
    context = _load_context(run_dir=run_dir, review_file=review_file, config=config)
    output_dir.mkdir(parents=True, exist_ok=True)

    assignments = [_build_assignment(movie, context=context, config=config) for movie in context["movies"]]
    cohort_records = _build_cohort_records(assignments=assignments, context=context, config=config)
    _apply_fallback_selection(assignments=assignments, cohort_records=cohort_records)
    coverage_report = _build_coverage_report(assignments=assignments, cohort_records=cohort_records, context=context, config=config)
    phase_recommendation = _phase_recommendation(coverage_report=coverage_report, context=context)
    activation_eligible = _activation_eligible(coverage_report=coverage_report, context=context, phase_recommendation=phase_recommendation)

    baselines = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "baseline_version": BASELINE_SCHEMA_VERSION,
        "input_run_id": context["run_manifest"]["run_id"],
        "input_file_hashes": context["input_hashes"],
        "configuration": {
            "era_buckets": [
                {"label": label, "start_year": start_year, "end_year": end_year}
                for label, start_year, end_year in config.era_buckets
            ],
            "level_thresholds": {level: config.threshold_for(level) for level, _name in COHORT_LEVELS},
            "global_cohort_key": GLOBAL_COHORT_KEY,
            "primary_genre_rule": "first provider-preserved normalized genre string when available, otherwise unknown_genre",
        },
        "review_status": context["review_status"],
        "activation_eligible": activation_eligible,
        "cohort_hierarchy": {
            "levels": [
                {"level": level, "name": name, "threshold": config.threshold_for(level)}
                for level, name in COHORT_LEVELS
            ],
            "fallback_order": ["level_1", "level_2", "level_3", "level_4", "unavailable"],
        },
        "cohort_records": cohort_records,
        "coverage_summary": coverage_report,
        "phase_recommendation": phase_recommendation,
        "source_provenance": {
            "run_script_version": context["run_manifest"].get("script_version"),
            "validator_version": context["validation_summary"].get("validator_version"),
            "sources_used": context["run_manifest"].get("sources_used", []),
            "source_urls": context["run_manifest"].get("source_urls", {}),
        },
    }

    baselines_path = output_dir / "cohort_baselines.json"
    assignments_path = output_dir / "movie_cohort_assignments.jsonl"
    manifest_path = output_dir / "cohort_baseline_manifest.json"
    coverage_path = output_dir / "cohort_coverage_report.json"

    baselines_path.write_text(json.dumps(baselines, indent=2, sort_keys=True), encoding="utf-8")
    _write_jsonl(assignments_path, assignments)
    coverage_path.write_text(json.dumps(coverage_report, indent=2, sort_keys=True), encoding="utf-8")

    manifest = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "baseline_version": BASELINE_SCHEMA_VERSION,
        "input_run_id": context["run_manifest"]["run_id"],
        "generated_at": datetime.now(UTC).isoformat(),
        "input_paths": {name: str(path) for name, path in context["input_paths"].items()},
        "input_file_hashes": context["input_hashes"],
        "output_file_hashes": {
            baselines_path.name: _sha256_path(baselines_path),
            assignments_path.name: _sha256_path(assignments_path),
            coverage_path.name: _sha256_path(coverage_path),
        },
        "record_counts": {
            "movies": len(assignments),
            "assignments": len(assignments),
            "cohort_records": len(cohort_records),
        },
        "cohort_counts": coverage_report["cohort_counts_by_level"],
        "warnings": context["warnings"],
        "configuration": baselines["configuration"],
        "source_provenance": baselines["source_provenance"],
        "manual_review_status": context["review_status"],
        "activation_eligible": activation_eligible,
        "phase_recommendation": phase_recommendation,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    return {
        "input_run_id": context["run_manifest"]["run_id"],
        "output_dir": output_dir,
        "cohort_baselines_path": baselines_path,
        "movie_assignments_path": assignments_path,
        "coverage_report_path": coverage_path,
        "manifest_path": manifest_path,
        "cohort_baselines": baselines,
        "cohort_records": cohort_records,
        "movie_assignments": assignments,
        "coverage_report": coverage_report,
        "phase_recommendation": phase_recommendation,
        "activation_eligible": activation_eligible,
        "manual_review_status": context["review_status"]["status"],
        "input_file_hashes": context["input_hashes"],
        "output_file_hashes": {
            baselines_path.name: _sha256_path(baselines_path),
            assignments_path.name: _sha256_path(assignments_path),
            coverage_path.name: _sha256_path(coverage_path),
            manifest_path.name: _sha256_path(manifest_path),
        },
    }


def _load_context(*, run_dir: Path, review_file: Path | None, config: CohortBaselineConfig) -> dict[str, Any]:
    input_paths = {
        "movies.jsonl": run_dir / "movies.jsonl",
        "wikidata_matches.jsonl": run_dir / "wikidata_matches.jsonl",
        "run_manifest.json": run_dir / "run_manifest.json",
        "coverage_summary.json": run_dir / "coverage_summary.json",
        "validated_matches.jsonl": run_dir / "validation" / "validated_matches.jsonl",
        "validation_summary.json": run_dir / "validation" / "validation_summary.json",
        "validation_manifest.json": run_dir / "validation" / "validation_manifest.json",
    }
    required = ("movies.jsonl", "wikidata_matches.jsonl", "run_manifest.json", "coverage_summary.json")
    for name in required:
        if not input_paths[name].exists():
            raise FileNotFoundError(f"required file missing: {name}")

    movies = _ordered_movies(_read_jsonl(input_paths["movies.jsonl"]))
    wikidata_matches = _read_jsonl(input_paths["wikidata_matches.jsonl"])
    run_manifest = _read_json(input_paths["run_manifest.json"])
    coverage_summary = _read_json(input_paths["coverage_summary.json"])
    validated_matches = _read_jsonl(input_paths["validated_matches.jsonl"]) if input_paths["validated_matches.jsonl"].exists() else []
    validation_summary = _read_json(input_paths["validation_summary.json"]) if input_paths["validation_summary.json"].exists() else {}
    validation_manifest = _read_json(input_paths["validation_manifest.json"]) if input_paths["validation_manifest.json"].exists() else {}

    input_hashes = {
        name: _sha256_path(path)
        for name, path in input_paths.items()
        if path.exists()
    }
    review_data = _load_review_data(review_file=review_file, validated_matches=validated_matches)
    warnings: list[str] = []
    if not validated_matches:
        warnings.append("validated_matches_missing")
    if review_data["status"] == "PENDING":
        warnings.append("manual_review_pending")
    if validation_summary.get("final_recommendation") == BLOCKED_BY_LOW_COVERAGE:
        warnings.append("validation_gate_blocked_by_low_coverage")

    movie_by_id = {str(movie["source_record_id"]): movie for movie in movies}
    wikidata_by_id = {str(row["tmdb_source_movie_id"]): row for row in wikidata_matches}
    validated_by_id = {str(row["tmdb_movie_id"]): row for row in validated_matches}

    return {
        "run_dir": run_dir,
        "input_paths": input_paths,
        "input_hashes": input_hashes,
        "movies": movies,
        "wikidata_by_id": wikidata_by_id,
        "validated_by_id": validated_by_id,
        "run_manifest": run_manifest,
        "coverage_summary": coverage_summary,
        "validation_summary": validation_summary,
        "validation_manifest": validation_manifest,
        "review_data": review_data,
        "review_status": _review_status(review_data=review_data, validation_summary=validation_summary),
        "warnings": warnings,
        "movie_by_id": movie_by_id,
        "config": config,
    }


def _build_assignment(movie: dict[str, Any], *, context: dict[str, Any], config: CohortBaselineConfig) -> dict[str, Any]:
    tmdb_movie_id = str(movie["source_record_id"])
    validated = context["validated_by_id"].get(tmdb_movie_id)
    wikidata = context["wikidata_by_id"].get(tmdb_movie_id, {})
    review = context["review_data"]["decisions_by_movie_id"].get(tmdb_movie_id)
    language = str(movie.get("original_language") or movie.get("requested_language") or "").strip().casefold()
    release_year = _as_year(movie.get("release_year"))
    era = assign_release_era(release_year, config=config)
    genres = _extract_normalized_genres(movie)
    primary_genre = genres[0] if genres else UNKNOWN_GENRE

    entity_resolution_status = (
        str(validated.get("validation_classification"))
        if validated
        else _fallback_entity_resolution_status(wikidata)
    )
    wikidata_signal_allowed = _wikidata_signal_allowed(entity_resolution_status=entity_resolution_status, review_decision=review)
    signal_eligibility = {
        "tmdb_rating": _rating_value(movie).exclusion_reason is None,
        "tmdb_rating_normalized": _normalized_rating_value(movie).exclusion_reason is None,
        "tmdb_vote_count": _vote_count_value(movie).exclusion_reason is None,
        "tmdb_vote_count_log1p": _vote_count_value(movie).exclusion_reason is None,
        "tmdb_popularity": _popularity_value(movie).exclusion_reason is None,
        "tmdb_popularity_log1p": _popularity_value(movie).exclusion_reason is None,
        "wikidata_identity": wikidata_signal_allowed,
    }

    return {
        "tmdb_movie_id": tmdb_movie_id,
        "title": movie.get("title"),
        "original_language": language,
        "release_year": release_year,
        "era": era,
        "primary_genre": primary_genre,
        "all_genres": genres,
        "level_1_cohort_key": build_cohort_key(level="level_1", language=language, era=era, primary_genre=primary_genre),
        "level_2_cohort_key": build_cohort_key(level="level_2", language=language, era=era, primary_genre=primary_genre),
        "level_3_cohort_key": build_cohort_key(level="level_3", language=language, era=era, primary_genre=primary_genre),
        "global_cohort_key": GLOBAL_COHORT_KEY,
        "selected_eligible_cohort_key": None,
        "selected_eligible_cohort_level": None,
        "fallback_reason": None,
        "entity_resolution_status": entity_resolution_status,
        "review_decision": review,
        "signal_eligibility_flags": signal_eligibility,
        "signal_values": {
            "tmdb_rating": _signal_entry(_rating_value(movie), scale="0-10"),
            "tmdb_rating_normalized": _signal_entry(_normalized_rating_value(movie), scale="0-1"),
            "tmdb_vote_count": _signal_entry(_vote_count_value(movie)),
            "tmdb_vote_count_log1p": _signal_entry(_log1p_value(_vote_count_value(movie))),
            "tmdb_popularity": _signal_entry(_popularity_value(movie)),
            "tmdb_popularity_log1p": _signal_entry(_log1p_value(_popularity_value(movie))),
        },
        "complete_identity_evidence": bool(validated.get("complete_identity_evidence")) if validated else False,
        "structurally_valid": bool(tmdb_movie_id and language in SUPPORTED_LANGUAGES),
    }


def assign_release_era(year: int | None, *, config: CohortBaselineConfig) -> str:
    if year is None:
        return UNKNOWN_YEAR
    for label, start_year, end_year in config.era_buckets:
        if start_year is not None and year < start_year:
            continue
        if end_year is not None and year > end_year:
            continue
        return label
    return UNKNOWN_YEAR


def build_cohort_key(*, level: str, language: str, era: str, primary_genre: str) -> str:
    language = _normalize_key_part(language)
    era = _normalize_key_part(era)
    primary_genre = _normalize_key_part(primary_genre)
    if level == "level_1":
        return f"language={language}|era={era}|genre={primary_genre}"
    if level == "level_2":
        return f"language={language}|era={era}"
    if level == "level_3":
        return f"language={language}"
    return GLOBAL_COHORT_KEY


def _build_cohort_records(
    *,
    assignments: list[dict[str, Any]],
    context: dict[str, Any],
    config: CohortBaselineConfig,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in assignments:
        grouped[("level_1", row["level_1_cohort_key"])].append(row)
        grouped[("level_2", row["level_2_cohort_key"])].append(row)
        grouped[("level_3", row["level_3_cohort_key"])].append(row)
        grouped[("level_4", row["global_cohort_key"])].append(row)

    records: list[dict[str, Any]] = []
    for level, _name in COHORT_LEVELS:
        for key in sorted(cohort_key for cohort_level, cohort_key in grouped if cohort_level == level):
            members = _ordered_assignments(grouped[(level, key)])
            eligible_records = [row for row in members if row["structurally_valid"]]
            record = {
                "cohort_key": key,
                "cohort_level": level,
                "dimensions": _cohort_dimensions(level=level, key=key, members=members),
                "sample_count": len(members),
                "eligible_record_count": len(eligible_records),
                "excluded_record_count": len(members) - len(eligible_records),
                "missing_signal_counts": _missing_signal_counts(members),
                "signal_statistics": _signal_statistics(members),
                "signal_exclusion_reasons": _signal_exclusion_reasons(members),
                "entity_resolution_counts": _entity_resolution_counts(members),
                "review_decision_counts": _review_decision_counts(members),
                "eligible_for_normalization": len(eligible_records) >= config.threshold_for(level),
                "fallback_to": _fallback_target(level=level, key=key, members=members),
                "fallback_reason": None,
                "input_run_id": context["run_manifest"]["run_id"],
                "input_file_hashes": context["input_hashes"],
                "manual_review_status": context["review_status"]["status"],
                "activation_eligible": False,
            }
            if not record["eligible_for_normalization"]:
                record["fallback_reason"] = (
                    f"sparse_cohort:{len(eligible_records)}<{config.threshold_for(level)}"
                )
            records.append(record)
    records.sort(key=lambda row: (_level_sort_key(row["cohort_level"]), row["cohort_key"]))
    return records


def _apply_fallback_selection(*, assignments: list[dict[str, Any]], cohort_records: list[dict[str, Any]]) -> None:
    eligibility_by_key = {row["cohort_key"]: row for row in cohort_records}
    for row in assignments:
        candidates = [
            ("level_1", row["level_1_cohort_key"]),
            ("level_2", row["level_2_cohort_key"]),
            ("level_3", row["level_3_cohort_key"]),
            ("level_4", row["global_cohort_key"]),
        ]
        for level, key in candidates:
            cohort = eligibility_by_key[key]
            if cohort["eligible_for_normalization"]:
                row["selected_eligible_cohort_key"] = key
                row["selected_eligible_cohort_level"] = level
                row["fallback_reason"] = None if level == "level_1" else f"fallback_from_level_1_to_{level}"
                break
        if row["selected_eligible_cohort_key"] is None:
            row["selected_eligible_cohort_level"] = "unavailable"
            row["fallback_reason"] = "no_eligible_cohort"


def _build_coverage_report(
    *,
    assignments: list[dict[str, Any]],
    cohort_records: list[dict[str, Any]],
    context: dict[str, Any],
    config: CohortBaselineConfig,
) -> dict[str, Any]:
    by_language = Counter(row["original_language"] for row in assignments)
    by_era = Counter(row["era"] for row in assignments)
    by_genre = Counter(row["primary_genre"] for row in assignments)
    fallback_counts = Counter(row["selected_eligible_cohort_level"] or "unavailable" for row in assignments)
    readiness = {
        language: _language_readiness(
            language=language,
            assignments=[row for row in assignments if row["original_language"] == language],
            cohort_records=cohort_records,
            context=context,
            config=config,
        )
        for language in sorted(by_language)
    }
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "input_run_id": context["run_manifest"]["run_id"],
        "manual_review_status": context["review_status"],
        "activation_eligible": False,
        "total_movies": len(assignments),
        "movies_per_language": dict(sorted(by_language.items())),
        "movies_per_era": dict(sorted(by_era.items())),
        "movies_per_genre": dict(sorted(by_genre.items())),
        "cohort_counts_by_level": {
            level: sum(1 for row in cohort_records if row["cohort_level"] == level)
            for level, _name in COHORT_LEVELS
        },
        "eligible_cohort_counts_by_level": {
            level: sum(1 for row in cohort_records if row["cohort_level"] == level and row["eligible_for_normalization"])
            for level, _name in COHORT_LEVELS
        },
        "sparse_cohort_counts_by_level": {
            level: sum(1 for row in cohort_records if row["cohort_level"] == level and not row["eligible_for_normalization"])
            for level, _name in COHORT_LEVELS
        },
        "fallback_counts": dict(sorted(fallback_counts.items())),
        "signal_coverage": {
            signal_name: _signal_coverage(assignments, signal_name)
            for signal_name in SIGNAL_ORDER
        },
        "entity_resolution_distribution": _entity_resolution_counts(assignments),
        "review_decision_distribution": _review_decision_counts(assignments),
        "per_language_readiness": readiness,
        "warnings": context["warnings"],
    }


def _phase_recommendation(*, coverage_report: dict[str, Any], context: dict[str, Any]) -> str:
    readiness_states = {row["readiness"] for row in coverage_report["per_language_readiness"].values()}
    if READINESS_ENTITY_BLOCKED in readiness_states or READINESS_SOURCE_BLOCKED in readiness_states:
        return PHASE_BLOCKED
    if any(row["structurally_valid_movies"] < DEFAULT_LEVEL_THRESHOLDS["level_3"] for row in coverage_report["per_language_readiness"].values()):
        return PHASE_EXPAND
    if context["review_status"]["status"] != "COMPLETED":
        return PHASE_REVIEW
    ready_languages = [
        language
        for language, row in coverage_report["per_language_readiness"].items()
        if row["readiness"] == READINESS_READY
    ]
    if len(ready_languages) == len(coverage_report["per_language_readiness"]):
        return PHASE_PROCEED
    if ready_languages:
        return PHASE_LIMITED
    return PHASE_EXPAND


def _activation_eligible(*, coverage_report: dict[str, Any], context: dict[str, Any], phase_recommendation: str) -> bool:
    if context["review_status"]["status"] != "COMPLETED":
        return False
    if phase_recommendation != PHASE_PROCEED:
        return False
    return all(
        row["readiness"] == READINESS_READY
        for row in coverage_report["per_language_readiness"].values()
    )


def _language_readiness(
    *,
    language: str,
    assignments: list[dict[str, Any]],
    cohort_records: list[dict[str, Any]],
    context: dict[str, Any],
    config: CohortBaselineConfig,
) -> dict[str, Any]:
    structurally_valid = [row for row in assignments if row["structurally_valid"]]
    language_cohort_key = build_cohort_key(level="level_3", language=language, era=UNKNOWN_YEAR, primary_genre=UNKNOWN_GENRE)
    language_cohort = next((row for row in cohort_records if row["cohort_key"] == language_cohort_key), None)
    source_errors = sum(1 for row in assignments if row["entity_resolution_status"] == SOURCE_ERROR)
    complete_identity_coverage = _safe_rate(
        sum(1 for row in assignments if row["complete_identity_evidence"]),
        len(assignments),
    )
    numeric_coverages = {
        signal_name: _signal_coverage(assignments, signal_name)["percentage"]
        for signal_name in ("tmdb_rating", "tmdb_vote_count", "tmdb_popularity")
    }
    useful_signal_coverages = [value for value in numeric_coverages.values() if value is not None]
    review_blocked = context["validation_summary"].get("final_recommendation") == BLOCKED_BY_ENTITY_RESOLUTION_QUALITY

    if source_errors and source_errors == len(assignments):
        readiness = READINESS_SOURCE_BLOCKED
    elif review_blocked:
        readiness = READINESS_ENTITY_BLOCKED
    elif len(structurally_valid) < config.threshold_for("level_3"):
        readiness = READINESS_INSUFFICIENT
    elif complete_identity_coverage is not None and complete_identity_coverage < 0.7:
        readiness = READINESS_LIMITED
    elif any(value is not None and value >= 0.7 for value in useful_signal_coverages) and context["review_status"]["status"] == "COMPLETED":
        readiness = READINESS_READY
    else:
        readiness = READINESS_LIMITED

    return {
        "readiness": readiness,
        "structurally_valid_movies": len(structurally_valid),
        "language_cohort_key": language_cohort_key,
        "language_cohort_eligible": bool(language_cohort and language_cohort["eligible_for_normalization"]),
        "complete_identity_coverage": complete_identity_coverage,
        "signal_coverage": numeric_coverages,
        "source_error_count": source_errors,
        "manual_review_status": context["review_status"]["status"],
    }


def _extract_normalized_genres(movie: dict[str, Any]) -> list[str]:
    # ponytail: only trust normalized string genres already present in evidence; upgrade to a curated TMDB-id mapping only after a persisted normalized taxonomy exists.
    for field_name in ("normalized_genres", "genres", "genre_names", "primary_genres"):
        value = movie.get(field_name)
        if isinstance(value, list):
            genres = [_normalize_key_part(item) for item in value if isinstance(item, str) and item.strip()]
            if genres:
                return genres
    return []


def _signal_statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        signal_name: _stats_for_signal(rows, signal_name)
        for signal_name in SIGNAL_ORDER
    }


def _stats_for_signal(rows: list[dict[str, Any]], signal_name: str) -> dict[str, Any]:
    values: list[float] = []
    missing_count = 0
    for row in rows:
        entry = row["signal_values"][signal_name]
        if entry["value"] is None:
            missing_count += 1
            continue
        values.append(float(entry["value"]))
    if not values:
        return {
            "count": 0,
            "missing_count": missing_count,
            "minimum": None,
            "maximum": None,
            "mean": None,
            "median": None,
            "p10": None,
            "p25": None,
            "p75": None,
            "p90": None,
            "population_stddev": None,
            "zero_count": None,
            "positive_count": None,
        }
    return {
        "count": len(values),
        "missing_count": missing_count,
        "minimum": round(min(values), 6),
        "maximum": round(max(values), 6),
        "mean": round(mean(values), 6),
        "median": round(median(values), 6),
        "p10": _percentile(values, 10),
        "p25": _percentile(values, 25),
        "p75": _percentile(values, 75),
        "p90": _percentile(values, 90),
        "population_stddev": round(pstdev(values), 6),
        "zero_count": sum(1 for value in values if value == 0),
        "positive_count": sum(1 for value in values if value > 0),
    }


def _missing_signal_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        signal_name: sum(1 for row in rows if row["signal_values"][signal_name]["value"] is None)
        for signal_name in SIGNAL_ORDER
    }


def _signal_exclusion_reasons(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    reasons: dict[str, Counter[str]] = {signal_name: Counter() for signal_name in SIGNAL_ORDER}
    for row in rows:
        for signal_name in SIGNAL_ORDER:
            reason = row["signal_values"][signal_name]["exclusion_reason"]
            if reason:
                reasons[signal_name][reason] += 1
    return {
        signal_name: dict(sorted(counter.items()))
        for signal_name, counter in reasons.items()
    }


def _entity_resolution_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter(row.get("entity_resolution_status") or "UNVALIDATED" for row in rows)
    return {status: counter.get(status, 0) for status in ENTITY_STATUS_ORDER}


def _review_decision_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter(str(row.get("review_decision") or "PENDING") for row in rows)
    return {status: counter.get(status, 0) for status in sorted(counter)}


def _fallback_target(*, level: str, key: str, members: list[dict[str, Any]]) -> str | None:
    sample = members[0]
    if level == "level_1":
        return sample["level_2_cohort_key"]
    if level == "level_2":
        return sample["level_3_cohort_key"]
    if level == "level_3":
        return sample["global_cohort_key"]
    return None


def _cohort_dimensions(*, level: str, key: str, members: list[dict[str, Any]]) -> dict[str, Any]:
    sample = members[0]
    dimensions = {"cohort_key": key}
    if level in {"level_1", "level_2", "level_3"}:
        dimensions["language"] = sample["original_language"]
    if level in {"level_1", "level_2"}:
        dimensions["era"] = sample["era"]
    if level == "level_1":
        dimensions["primary_genre"] = sample["primary_genre"]
    if level == "level_4":
        dimensions["scope"] = "regional_sample"
    return dimensions


def _signal_coverage(rows: list[dict[str, Any]], signal_name: str) -> dict[str, Any]:
    count = sum(1 for row in rows if row["signal_values"][signal_name]["value"] is not None)
    return {
        "count": count,
        "denominator": len(rows),
        "percentage": _safe_rate(count, len(rows)),
    }


def _normalize_key_part(value: str) -> str:
    return (
        str(value)
        .strip()
        .casefold()
        .replace("|", "_")
        .replace("=", "_")
        .replace("/", "_")
        .replace(" ", "_")
    ) or "unknown"


def _rating_value(movie: dict[str, Any]) -> SignalValue:
    rating_scale = movie.get("rating_scale")
    if rating_scale not in (None, "", "0-10"):
        return SignalValue(0.0, "unknown_rating_scale")
    value = movie.get("vote_average")
    if isinstance(value, bool):
        return SignalValue(0.0, "boolean_not_allowed")
    if value is None:
        return SignalValue(0.0, "missing")
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return SignalValue(0.0, "malformed_number")
    if not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
        return SignalValue(0.0, "invalid_number")
    if value < 0 or value > 10:
        return SignalValue(0.0, "out_of_range")
    return SignalValue(float(value), None)


def _normalized_rating_value(movie: dict[str, Any]) -> SignalValue:
    rating = _rating_value(movie)
    if rating.exclusion_reason is not None:
        return SignalValue(0.0, rating.exclusion_reason)
    return SignalValue(round(rating.value / 10.0, 6), None)


def _vote_count_value(movie: dict[str, Any]) -> SignalValue:
    value = movie.get("vote_count")
    if isinstance(value, bool):
        return SignalValue(0.0, "boolean_not_allowed")
    if value is None:
        return SignalValue(0.0, "missing")
    if isinstance(value, str):
        if not value.strip().isdigit():
            return SignalValue(0.0, "malformed_number")
        value = int(value)
    if not isinstance(value, int):
        return SignalValue(0.0, "invalid_integer")
    if value < 0:
        return SignalValue(0.0, "negative_not_allowed")
    return SignalValue(float(value), None)


def _popularity_value(movie: dict[str, Any]) -> SignalValue:
    value = movie.get("popularity")
    if isinstance(value, bool):
        return SignalValue(0.0, "boolean_not_allowed")
    if value is None:
        return SignalValue(0.0, "missing")
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return SignalValue(0.0, "malformed_number")
    if not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
        return SignalValue(0.0, "invalid_number")
    if value < 0:
        return SignalValue(0.0, "negative_not_allowed")
    return SignalValue(float(value), None)


def _log1p_value(signal: SignalValue) -> SignalValue:
    if signal.exclusion_reason is not None:
        return SignalValue(0.0, signal.exclusion_reason)
    if signal.value < 0:
        return SignalValue(0.0, "negative_not_allowed")
    return SignalValue(round(math.log1p(signal.value), 6), None)


def _signal_entry(signal: SignalValue, *, scale: str | None = None) -> dict[str, Any]:
    return {
        "value": None if signal.exclusion_reason is not None else signal.value,
        "scale": scale,
        "exclusion_reason": signal.exclusion_reason,
    }


def _fallback_entity_resolution_status(wikidata: dict[str, Any]) -> str:
    match_status = wikidata.get("match_status")
    if match_status == "EXACT_IDENTIFIER_MATCH":
        return EXACT_MATCH_WITH_WARNINGS
    if match_status == "NO_MATCH":
        return "NO_MATCH"
    if match_status == "AMBIGUOUS_REVIEW_REQUIRED":
        return "AMBIGUOUS_REVIEW_REQUIRED"
    if match_status == "SOURCE_ERROR":
        return SOURCE_ERROR
    return "UNVALIDATED"


def _wikidata_signal_allowed(*, entity_resolution_status: str, review_decision: str | None) -> bool:
    if review_decision == "REJECTED":
        return False
    if entity_resolution_status == VALIDATED_EXACT_MATCH:
        return True
    if entity_resolution_status == EXACT_MATCH_WITH_WARNINGS:
        return review_decision in {None, "", "CONFIRMED"}
    return False


def _load_review_data(*, review_file: Path | None, validated_matches: list[dict[str, Any]]) -> dict[str, Any]:
    if review_file is None:
        return {"review_file": None, "decisions_by_movie_id": {}, "reviewed_count": 0, "unresolved_count": 0, "status": "PENDING"}
    matches_by_id = {str(row["tmdb_movie_id"]): row for row in validated_matches}
    decisions_by_movie_id: dict[str, str] = {}
    unresolved_count = 0
    reviewed_count = 0
    with Path(review_file).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            decision = str(row.get("reviewer_decision") or "").strip()
            if decision not in ACCEPTED_REVIEW_DECISIONS:
                raise ValueError(f"invalid reviewer decision: {decision}")
            tmdb_movie_id = str(row.get("tmdb_movie_id") or "").strip()
            if not tmdb_movie_id or not decision:
                continue
            if tmdb_movie_id not in matches_by_id:
                continue
            decisions_by_movie_id[tmdb_movie_id] = decision
            reviewed_count += 1
            if decision == "NEEDS_FOLLOW_UP":
                unresolved_count += 1
    if reviewed_count == 0:
        status = "PENDING"
    else:
        status = "COMPLETED" if unresolved_count == 0 else "PARTIAL"
    return {
        "review_file": str(review_file),
        "decisions_by_movie_id": decisions_by_movie_id,
        "reviewed_count": reviewed_count,
        "unresolved_count": unresolved_count,
        "status": status,
    }


def _review_status(*, review_data: dict[str, Any], validation_summary: dict[str, Any]) -> dict[str, Any]:
    if review_data["status"] == "PENDING":
        return {
            "status": "PENDING",
            "review_file": None,
            "reviewed_count": 0,
            "unresolved_count": 0,
            "activation_eligible": False,
        }
    return {
        "status": review_data["status"],
        "review_file": review_data["review_file"],
        "reviewed_count": review_data["reviewed_count"],
        "unresolved_count": review_data["unresolved_count"],
        "activation_eligible": False,
        "validation_recommendation": validation_summary.get("final_recommendation"),
    }


def _ordered_movies(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("original_language") or row.get("requested_language") or ""),
            row.get("release_year") if isinstance(row.get("release_year"), int) else 10**9,
            str(row.get("normalized_title") or ""),
            str(row.get("source_record_id") or ""),
        ),
    )


def _ordered_assignments(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            row["original_language"],
            row["release_year"] if row["release_year"] is not None else 10**9,
            str(row.get("title") or ""),
            row["tmdb_movie_id"],
        ),
    )


def _level_sort_key(level: str) -> int:
    return {name: index for index, (name, _value) in enumerate(COHORT_LEVELS, start=1)}.get(level, 99)


def _percentile(values: list[float], percentile: int) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 6)
    rank = (len(ordered) - 1) * (percentile / 100)
    lower_index = int(math.floor(rank))
    upper_index = int(math.ceil(rank))
    if lower_index == upper_index:
        return round(ordered[lower_index], 6)
    fraction = rank - lower_index
    value = ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * fraction
    return round(value, 6)


def _as_year(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and len(value) >= 4 and value[:4].isdigit():
        return int(value[:4])
    return None


def _safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


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
