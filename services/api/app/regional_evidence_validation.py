from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.regional_evidence import (
    WIKIDATA_AMBIGUOUS,
    WIKIDATA_ERROR,
    WIKIDATA_EXACT,
    WIKIDATA_NONE,
    normalize_evidence_title,
)

VALIDATED_EXACT_MATCH = "VALIDATED_EXACT_MATCH"
EXACT_MATCH_WITH_WARNINGS = "EXACT_MATCH_WITH_WARNINGS"
AMBIGUOUS_REVIEW_REQUIRED = "AMBIGUOUS_REVIEW_REQUIRED"
NO_MATCH = "NO_MATCH"
SOURCE_ERROR = "SOURCE_ERROR"

GO_FOR_EXPANDED_SAMPLE = "GO_FOR_EXPANDED_SAMPLE"
GO_WITH_WARNINGS = "GO_WITH_WARNINGS"
MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
BLOCKED_BY_LOW_COVERAGE = "BLOCKED_BY_LOW_COVERAGE"
BLOCKED_BY_DATA_INTEGRITY = "BLOCKED_BY_DATA_INTEGRITY"

MISSING_NATIVE_LABEL = "MISSING_NATIVE_LABEL"
MISSING_ALIASES = "MISSING_ALIASES"
MISSING_IMDB_ID = "MISSING_IMDB_ID"
MISSING_COUNTRY = "MISSING_COUNTRY"
MISSING_DIRECTOR = "MISSING_DIRECTOR"
MISSING_RELEASE_YEAR = "MISSING_RELEASE_YEAR"
MISSING_ORIGINAL_LANGUAGE = "MISSING_ORIGINAL_LANGUAGE"
YEAR_CONFLICT = "YEAR_CONFLICT"
LANGUAGE_CONFLICT = "LANGUAGE_CONFLICT"
TITLE_CONFLICT = "TITLE_CONFLICT"
DUPLICATE_QID = "DUPLICATE_QID"
TMDB_ID_CONFLICT = "TMDB_ID_CONFLICT"
MISSING_WIKIDATA_QID = "MISSING_WIKIDATA_QID"

VALIDATOR_VERSION = "regional-evidence-validation-v1"
DEFAULT_REVIEW_SAMPLE_SIZE = 10
DEFAULT_MINIMUM_EXACT_COVERAGE = 0.70
DEFAULT_MAXIMUM_AMBIGUOUS_ERROR_RATE = 0.10
ACCEPTED_REVIEW_DECISIONS = {"", "CONFIRMED", "REJECTED", "NEEDS_FOLLOW_UP"}
CRITICAL_WARNINGS = {DUPLICATE_QID, TMDB_ID_CONFLICT, YEAR_CONFLICT, LANGUAGE_CONFLICT, TITLE_CONFLICT}
REQUIRED_FILES = (
    "movies.jsonl",
    "wikidata_matches.jsonl",
    "coverage_summary.json",
    "run_manifest.json",
)
OPTIONAL_FILES = (
    "national_awards_records.jsonl",
    "recognition_match_candidates.jsonl",
)
CLASSIFICATION_ORDER = (
    VALIDATED_EXACT_MATCH,
    EXACT_MATCH_WITH_WARNINGS,
    AMBIGUOUS_REVIEW_REQUIRED,
    NO_MATCH,
    SOURCE_ERROR,
)
REVIEW_SAMPLE_COLUMNS = (
    "tmdb_movie_id",
    "wikidata_qid",
    "language",
    "tmdb_title",
    "tmdb_original_title",
    "wikidata_label",
    "wikidata_aliases",
    "tmdb_release_year",
    "wikidata_release_year",
    "director",
    "country",
    "validation_classification",
    "warnings",
    "reviewer_decision",
    "reviewer_notes",
)
LANGUAGE_LABELS = {
    "mr": {"marathi"},
    "ml": {"malayalam"},
    "ta": {"tamil"},
    "te": {"telugu"},
    "kn": {"kannada"},
    "hi": {"hindi"},
    "bn": {"bengali", "bangla"},
    "en": {"english"},
}
SECRET_PATTERNS = (
    re.compile(r"TMDB_API_READ_ACCESS_TOKEN", re.IGNORECASE),
    re.compile(r"DATA_GOV_IN_API_KEY", re.IGNORECASE),
    re.compile(r"\bAuthorization\b", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{8,}", re.IGNORECASE),
    re.compile(r"(?:api[_-]?key|token)\s*[:=]\s*[A-Za-z0-9._\-]{8,}", re.IGNORECASE),
)


@dataclass(frozen=True)
class ValidationThresholds:
    minimum_exact_coverage: float = DEFAULT_MINIMUM_EXACT_COVERAGE
    maximum_ambiguous_error_rate: float = DEFAULT_MAXIMUM_AMBIGUOUS_ERROR_RATE
    strict: bool = False


@dataclass
class ValidationContext:
    run_dir: Path
    validation_dir: Path
    source_run_id: str
    requested_languages: list[str]
    movies: list[dict[str, Any]]
    wikidata_matches: list[dict[str, Any]]
    coverage_summary: dict[str, Any]
    manifest: dict[str, Any]
    awards_records: list[dict[str, Any]]
    recognition_records: list[dict[str, Any]]
    integrity_errors: list[str]
    secret_findings: list[str]
    input_hashes: dict[str, str]
    started_at: str


def validate_regional_evidence_run(
    *,
    run_dir: Path,
    review_sample_size: int = DEFAULT_REVIEW_SAMPLE_SIZE,
    review_file: Path | None = None,
    thresholds: ValidationThresholds | None = None,
) -> dict[str, Any]:
    thresholds = thresholds or ValidationThresholds()
    context = _load_context(Path(run_dir))

    validated_matches, warning_counts = _validate_matches(context)
    coverage = _build_validation_coverage(context.requested_languages, validated_matches)
    review_rows = _build_review_sample(
        validated_matches=validated_matches,
        requested_languages=context.requested_languages,
        sample_size=review_sample_size,
    )
    review_stats = _load_review_stats(review_file) if review_file is not None else _empty_review_stats()
    recommendation = _final_recommendation(
        integrity_errors=context.integrity_errors,
        secret_findings=context.secret_findings,
        coverage=coverage,
        warning_counts=warning_counts,
        thresholds=thresholds,
    )

    validation_dir = context.validation_dir
    validation_dir.mkdir(parents=True, exist_ok=True)
    validated_matches_path = validation_dir / "validated_matches.jsonl"
    validation_summary_path = validation_dir / "validation_summary.json"
    review_sample_path = validation_dir / "review_sample.csv"
    validation_manifest_path = validation_dir / "validation_manifest.json"

    _write_jsonl(validated_matches_path, validated_matches)
    _write_review_sample_csv(review_sample_path, review_rows)

    classification_counts = Counter(match["validation_classification"] for match in validated_matches)
    validation_run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    validation_summary = {
        "source_run_id": context.source_run_id,
        "validation_run_id": validation_run_id,
        "validator_version": VALIDATOR_VERSION,
        "classification_counts": {key: classification_counts.get(key, 0) for key in CLASSIFICATION_ORDER},
        "warning_counts": dict(sorted(warning_counts.items())),
        "integrity_errors": context.integrity_errors,
        "secret_findings": context.secret_findings,
        "coverage": coverage,
        "review_stats": review_stats,
        "final_recommendation": recommendation,
    }
    validation_summary_path.write_text(json.dumps(validation_summary, indent=2, sort_keys=True), encoding="utf-8")

    completed_at = datetime.now(UTC).isoformat()
    output_hashes = {
        validated_matches_path.name: _sha256_path(validated_matches_path),
        validation_summary_path.name: _sha256_path(validation_summary_path),
        review_sample_path.name: _sha256_path(review_sample_path),
    }
    validation_manifest = {
        "source_run_id": context.source_run_id,
        "validation_run_id": validation_run_id,
        "validator_version": VALIDATOR_VERSION,
        "started_at": context.started_at,
        "completed_at": completed_at,
        "input_file_hashes": context.input_hashes,
        "output_file_hashes": output_hashes,
        "record_counts": {
            "movies": len(context.movies),
            "wikidata_matches": len(context.wikidata_matches),
            "validated_matches": len(validated_matches),
            "review_sample_rows": len(review_rows),
        },
        "classification_counts": validation_summary["classification_counts"],
        "warning_counts": validation_summary["warning_counts"],
        "error_counts": {
            "integrity_errors": len(context.integrity_errors),
            "secret_findings": len(context.secret_findings),
        },
        "thresholds_used": {
            "minimum_exact_coverage": thresholds.minimum_exact_coverage,
            "maximum_ambiguous_error_rate": thresholds.maximum_ambiguous_error_rate,
        },
        "strict_mode": thresholds.strict,
        "review_sample_size": review_sample_size,
        "final_recommendation": recommendation,
    }
    validation_manifest_path.write_text(json.dumps(validation_manifest, indent=2, sort_keys=True), encoding="utf-8")

    return {
        "context": context,
        "validated_matches": validated_matches,
        "validation_summary": validation_summary,
        "validation_manifest": validation_manifest,
        "review_sample_path": review_sample_path,
        "review_stats": review_stats,
        "final_recommendation": recommendation,
        "validation_output_dir": validation_dir,
    }


def _load_context(run_dir: Path) -> ValidationContext:
    run_dir = run_dir.resolve()
    started_at = datetime.now(UTC).isoformat()
    paths = {name: run_dir / name for name in REQUIRED_FILES + OPTIONAL_FILES}
    input_hashes: dict[str, str] = {}
    integrity_errors: list[str] = []

    for name in REQUIRED_FILES:
        if not paths[name].exists():
            raise FileNotFoundError(f"required file missing: {name}")
        input_hashes[name] = _sha256_path(paths[name])

    movies = _read_jsonl(paths["movies.jsonl"])
    wikidata_matches = _read_jsonl(paths["wikidata_matches.jsonl"])
    coverage_summary = _read_json(paths["coverage_summary.json"])
    manifest = _read_json(paths["run_manifest.json"])
    awards_records = _read_jsonl(paths["national_awards_records.jsonl"]) if paths["national_awards_records.jsonl"].exists() else []
    recognition_records = (
        _read_jsonl(paths["recognition_match_candidates.jsonl"])
        if paths["recognition_match_candidates.jsonl"].exists()
        else []
    )
    for name in OPTIONAL_FILES:
        if paths[name].exists():
            input_hashes[name] = _sha256_path(paths[name])

    if manifest.get("run_id") != run_dir.name:
        integrity_errors.append("manifest_run_id_mismatch")

    manifest_counts = manifest.get("record_counts", {})
    _check_manifest_count(integrity_errors, manifest_counts, "movies", len(movies))
    _check_manifest_count(integrity_errors, manifest_counts, "wikidata_matches", len(wikidata_matches))
    _check_manifest_count(integrity_errors, manifest_counts, "national_awards_records", len(awards_records))
    _check_manifest_count(integrity_errors, manifest_counts, "recognition_match_candidates", len(recognition_records))
    _check_manifest_hashes(integrity_errors, run_dir, manifest.get("output_hashes", {}))

    movie_ids = [str(movie.get("source_record_id", "")) for movie in movies]
    if len(movie_ids) != len(set(movie_ids)):
        integrity_errors.append("duplicate_tmdb_movie_ids")

    requested_languages = [str(value).strip().lower() for value in manifest.get("requested_languages", []) if str(value).strip()]
    if requested_languages:
        movie_languages = {str(movie.get("requested_language", "")).strip().lower() for movie in movies}
        missing_languages = sorted(set(requested_languages) - movie_languages)
        unexpected_languages = sorted(movie_languages - set(requested_languages))
        if missing_languages:
            integrity_errors.append(f"missing_requested_language_representation:{','.join(missing_languages)}")
        if unexpected_languages:
            integrity_errors.append(f"unexpected_requested_language_in_movies:{','.join(unexpected_languages)}")

    movies_by_id = {str(movie.get("source_record_id")): movie for movie in movies}
    resolutions_by_tmdb_id: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in wikidata_matches:
        tmdb_id = str(record.get("tmdb_source_movie_id", ""))
        if tmdb_id not in movies_by_id:
            integrity_errors.append(f"wikidata_record_unknown_tmdb_id:{tmdb_id}")
        resolutions_by_tmdb_id[tmdb_id].append(record)
    for movie_id in movies_by_id:
        if len(resolutions_by_tmdb_id.get(movie_id, [])) != 1:
            integrity_errors.append(f"wikidata_resolution_count_invalid:{movie_id}")

    secret_findings: list[str] = []
    for name in REQUIRED_FILES + OPTIONAL_FILES:
        path = paths[name]
        if path.exists():
            secret_findings.extend(_detect_secrets(path))

    return ValidationContext(
        run_dir=run_dir,
        validation_dir=run_dir / "validation",
        source_run_id=run_dir.name,
        requested_languages=requested_languages,
        movies=movies,
        wikidata_matches=wikidata_matches,
        coverage_summary=coverage_summary,
        manifest=manifest,
        awards_records=awards_records,
        recognition_records=recognition_records,
        integrity_errors=sorted(set(integrity_errors)),
        secret_findings=sorted(set(secret_findings)),
        input_hashes=input_hashes,
        started_at=started_at,
    )


def _validate_matches(context: ValidationContext) -> tuple[list[dict[str, Any]], Counter[str]]:
    movies_by_id = {str(movie["source_record_id"]): movie for movie in context.movies}
    resolutions_by_tmdb_id: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in context.wikidata_matches:
        resolutions_by_tmdb_id[str(record.get("tmdb_source_movie_id", ""))].append(record)

    qid_counts = Counter(
        str(record.get("wikidata_qid"))
        for record in context.wikidata_matches
        if record.get("wikidata_qid")
    )
    warning_counts: Counter[str] = Counter()
    validated_matches: list[dict[str, Any]] = []

    for tmdb_movie_id in sorted(movies_by_id):
        movie = movies_by_id[tmdb_movie_id]
        resolutions = resolutions_by_tmdb_id.get(tmdb_movie_id, [])
        wikidata = resolutions[0] if resolutions else _missing_resolution_record(tmdb_movie_id)
        warnings = sorted(_warnings_for_match(movie, wikidata, qid_counts, len(resolutions)))
        classification = _classification_for_match(wikidata, warnings)
        for warning in warnings:
            warning_counts[warning] += 1
        validated_matches.append(
            {
                "tmdb_movie_id": tmdb_movie_id,
                "wikidata_qid": wikidata.get("wikidata_qid"),
                "language": movie.get("requested_language"),
                "tmdb_title": movie.get("title"),
                "tmdb_original_title": movie.get("original_title"),
                "wikidata_label": wikidata.get("english_label"),
                "wikidata_aliases": [item["value"] for item in wikidata.get("alternate_titles", []) if isinstance(item, dict)],
                "tmdb_release_year": movie.get("release_year"),
                "wikidata_release_year": _year_from_value(wikidata.get("publication_date")),
                "director": ", ".join(wikidata.get("directors", [])) or None,
                "country": ", ".join(wikidata.get("countries_of_origin", [])) or None,
                "validation_classification": classification,
                "warnings": warnings,
                "complete_identity_evidence": _complete_identity_evidence(movie, wikidata),
                "match_status": wikidata.get("match_status"),
            }
        )
    return validated_matches, warning_counts


def _warnings_for_match(
    movie: dict[str, Any],
    wikidata: dict[str, Any],
    qid_counts: Counter[str],
    resolution_count: int,
) -> set[str]:
    status = wikidata.get("match_status")
    if status in {WIKIDATA_NONE, WIKIDATA_ERROR}:
        return set()

    warnings: set[str] = set()
    qid = wikidata.get("wikidata_qid")
    if not qid:
        warnings.add(MISSING_WIKIDATA_QID)
    elif qid_counts[str(qid)] > 1:
        warnings.add(DUPLICATE_QID)
    if resolution_count > 1:
        warnings.add(DUPLICATE_QID)

    wikidata_tmdb_id = wikidata.get("wikidata_tmdb_id", wikidata.get("tmdb_source_movie_id"))
    if str(wikidata_tmdb_id) != str(movie.get("source_record_id")):
        warnings.add(TMDB_ID_CONFLICT)

    native_language = str(movie.get("original_language") or "").strip().lower()
    if native_language and not _has_language_label(wikidata.get("titles", []), native_language):
        warnings.add(MISSING_NATIVE_LABEL)
    if not wikidata.get("alternate_titles"):
        warnings.add(MISSING_ALIASES)
    if not wikidata.get("imdb_id"):
        warnings.add(MISSING_IMDB_ID)
    if not wikidata.get("countries_of_origin"):
        warnings.add(MISSING_COUNTRY)
    if not wikidata.get("directors"):
        warnings.add(MISSING_DIRECTOR)

    movie_year = movie.get("release_year")
    wikidata_year = _year_from_value(wikidata.get("publication_date"))
    if wikidata_year is None:
        warnings.add(MISSING_RELEASE_YEAR)
    elif movie_year is not None and wikidata_year != movie_year:
        warnings.add(YEAR_CONFLICT)

    if not wikidata.get("original_languages"):
        warnings.add(MISSING_ORIGINAL_LANGUAGE)
    elif native_language and not _language_compatible(native_language, wikidata.get("original_languages", [])):
        warnings.add(LANGUAGE_CONFLICT)

    if not _title_compatible(movie, wikidata):
        warnings.add(TITLE_CONFLICT)

    return warnings


def _classification_for_match(wikidata: dict[str, Any], warnings: list[str]) -> str:
    status = wikidata.get("match_status")
    if status == WIKIDATA_ERROR:
        return SOURCE_ERROR
    if status == WIKIDATA_NONE:
        return NO_MATCH
    if status == WIKIDATA_AMBIGUOUS:
        return AMBIGUOUS_REVIEW_REQUIRED
    if any(warning in CRITICAL_WARNINGS for warning in warnings):
        return AMBIGUOUS_REVIEW_REQUIRED
    if warnings:
        return EXACT_MATCH_WITH_WARNINGS
    return VALIDATED_EXACT_MATCH


def _complete_identity_evidence(movie: dict[str, Any], wikidata: dict[str, Any]) -> bool:
    return all(
        (
            bool(movie.get("source_record_id")),
            bool(wikidata.get("wikidata_qid")),
            bool(_usable_titles(movie, wikidata)),
            movie.get("release_year") is not None or _year_from_value(wikidata.get("publication_date")) is not None,
            bool(movie.get("original_language") or wikidata.get("original_languages")),
        )
    )


def _build_validation_coverage(
    requested_languages: list[str],
    validated_matches: list[dict[str, Any]],
) -> dict[str, Any]:
    per_language: dict[str, dict[str, Any]] = {}
    for language in requested_languages:
        language_matches = [row for row in validated_matches if row.get("language") == language]
        per_language[language] = _coverage_metrics(language_matches)
    return {
        "per_language": per_language,
        "aggregate": _coverage_metrics(validated_matches),
    }


def _coverage_metrics(matches: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(matches)
    classifications = Counter(match["validation_classification"] for match in matches)
    native_label = sum(1 for match in matches if MISSING_NATIVE_LABEL not in match["warnings"])
    alternate_label = sum(1 for match in matches if MISSING_ALIASES not in match["warnings"])
    imdb_id = sum(1 for match in matches if MISSING_IMDB_ID not in match["warnings"])
    country = sum(1 for match in matches if MISSING_COUNTRY not in match["warnings"])
    director = sum(1 for match in matches if MISSING_DIRECTOR not in match["warnings"])
    release_year = sum(1 for match in matches if MISSING_RELEASE_YEAR not in match["warnings"])
    original_language = sum(1 for match in matches if MISSING_ORIGINAL_LANGUAGE not in match["warnings"])
    complete_identity = sum(1 for match in matches if match["complete_identity_evidence"])
    manual_review = sum(1 for match in matches if match["validation_classification"] == AMBIGUOUS_REVIEW_REQUIRED)
    return {
        "total_sampled_movies": total,
        "validated_exact_matches": classifications.get(VALIDATED_EXACT_MATCH, 0),
        "exact_matches_with_warnings": classifications.get(EXACT_MATCH_WITH_WARNINGS, 0),
        "ambiguous_matches": classifications.get(AMBIGUOUS_REVIEW_REQUIRED, 0),
        "no_matches": classifications.get(NO_MATCH, 0),
        "source_errors": classifications.get(SOURCE_ERROR, 0),
        "native_label_coverage": _metric(native_label, total),
        "alternate_label_coverage": _metric(alternate_label, total),
        "imdb_id_coverage": _metric(imdb_id, total),
        "country_coverage": _metric(country, total),
        "director_coverage": _metric(director, total),
        "release_year_coverage": _metric(release_year, total),
        "original_language_coverage": _metric(original_language, total),
        "complete_identity_coverage": _metric(complete_identity, total),
        "records_requiring_manual_review": _metric(manual_review, total),
    }


def _build_review_sample(
    *,
    validated_matches: list[dict[str, Any]],
    requested_languages: list[str],
    sample_size: int,
) -> list[dict[str, Any]]:
    sample_size = max(0, sample_size)
    grouped: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for match in sorted(
        validated_matches,
        key=lambda row: (row["validation_classification"], row.get("language") or "", row["tmdb_movie_id"]),
    ):
        grouped[(row_language(match), match["validation_classification"])].append(match)

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for classification in CLASSIFICATION_ORDER:
        for language in requested_languages:
            candidates = grouped.get((language, classification), [])
            if candidates and candidates[0]["tmdb_movie_id"] not in seen:
                rows.append(_review_row(candidates[0]))
                seen.add(candidates[0]["tmdb_movie_id"])
            if len(rows) >= sample_size:
                return rows[:sample_size]

    for match in sorted(
        validated_matches,
        key=lambda row: (row.get("language") or "", row["validation_classification"], row["tmdb_movie_id"]),
    ):
        if match["tmdb_movie_id"] in seen:
            continue
        rows.append(_review_row(match))
        seen.add(match["tmdb_movie_id"])
        if len(rows) >= sample_size:
            break
    return rows[:sample_size]


def _review_row(match: dict[str, Any]) -> dict[str, Any]:
    return {
        "tmdb_movie_id": match["tmdb_movie_id"],
        "wikidata_qid": match.get("wikidata_qid") or "",
        "language": match.get("language") or "",
        "tmdb_title": match.get("tmdb_title") or "",
        "tmdb_original_title": match.get("tmdb_original_title") or "",
        "wikidata_label": match.get("wikidata_label") or "",
        "wikidata_aliases": " | ".join(match.get("wikidata_aliases", [])),
        "tmdb_release_year": match.get("tmdb_release_year") or "",
        "wikidata_release_year": match.get("wikidata_release_year") or "",
        "director": match.get("director") or "",
        "country": match.get("country") or "",
        "validation_classification": match["validation_classification"],
        "warnings": ",".join(match["warnings"]),
        "reviewer_decision": "",
        "reviewer_notes": "",
    }


def _write_review_sample_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(REVIEW_SAMPLE_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def _load_review_stats(review_file: Path) -> dict[str, Any]:
    with Path(review_file).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        decisions: list[str] = []
        for row in reader:
            decision = str(row.get("reviewer_decision") or "").strip()
            if decision not in ACCEPTED_REVIEW_DECISIONS:
                raise ValueError(f"invalid reviewer decision: {decision}")
            if decision:
                decisions.append(decision)
    reviewed_count = len(decisions)
    confirmed_count = sum(1 for decision in decisions if decision == "CONFIRMED")
    rejected_count = sum(1 for decision in decisions if decision == "REJECTED")
    follow_up_count = sum(1 for decision in decisions if decision == "NEEDS_FOLLOW_UP")
    return {
        "reviewed_count": reviewed_count,
        "confirmed_count": confirmed_count,
        "rejected_count": rejected_count,
        "follow_up_count": follow_up_count,
        "confirmation_rate": _safe_rate(confirmed_count, reviewed_count),
        "rejection_rate": _safe_rate(rejected_count, reviewed_count),
    }


def _empty_review_stats() -> dict[str, Any]:
    return {
        "reviewed_count": 0,
        "confirmed_count": 0,
        "rejected_count": 0,
        "follow_up_count": 0,
        "confirmation_rate": None,
        "rejection_rate": None,
    }


def _final_recommendation(
    *,
    integrity_errors: list[str],
    secret_findings: list[str],
    coverage: dict[str, Any],
    warning_counts: Counter[str],
    thresholds: ValidationThresholds,
) -> str:
    if integrity_errors or secret_findings:
        return BLOCKED_BY_DATA_INTEGRITY

    aggregate = coverage["aggregate"]
    total = aggregate["total_sampled_movies"]
    exact_coverage = _safe_rate(
        aggregate["validated_exact_matches"] + aggregate["exact_matches_with_warnings"],
        total,
    ) or 0.0
    ambiguous_error_rate = _safe_rate(
        aggregate["ambiguous_matches"] + aggregate["source_errors"],
        total,
    ) or 0.0
    if exact_coverage < thresholds.minimum_exact_coverage:
        return BLOCKED_BY_LOW_COVERAGE
    if ambiguous_error_rate > thresholds.maximum_ambiguous_error_rate:
        return MANUAL_REVIEW_REQUIRED
    if (
        aggregate["exact_matches_with_warnings"] > 0
        or aggregate["no_matches"] > 0
        or aggregate["ambiguous_matches"] > 0
        or aggregate["source_errors"] > 0
        or bool(warning_counts)
    ):
        return GO_WITH_WARNINGS
    return GO_FOR_EXPANDED_SAMPLE


def row_language(match: dict[str, Any]) -> str:
    return str(match.get("language") or "")


def _metric(count: int, denominator: int) -> dict[str, Any]:
    return {
        "count": count,
        "denominator": denominator,
        "percentage": _safe_rate(count, denominator),
    }


def _safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _usable_titles(movie: dict[str, Any], wikidata: dict[str, Any]) -> set[str]:
    titles: set[str] = set()
    for value in (movie.get("title"), movie.get("original_title"), wikidata.get("english_label")):
        if isinstance(value, str) and value.strip():
            titles.add(normalize_evidence_title(value))
    for collection_name in ("titles", "alternate_titles"):
        for item in wikidata.get(collection_name, []):
            if isinstance(item, dict) and item.get("normalized"):
                titles.add(str(item["normalized"]))
    return titles


def _title_compatible(movie: dict[str, Any], wikidata: dict[str, Any]) -> bool:
    movie_titles = {
        normalize_evidence_title(value)
        for value in (movie.get("title"), movie.get("original_title"))
        if isinstance(value, str) and value.strip()
    }
    wikidata_titles = {
        str(item.get("normalized"))
        for item in wikidata.get("titles", []) + wikidata.get("alternate_titles", [])
        if isinstance(item, dict) and item.get("normalized")
    }
    english_label = wikidata.get("english_label")
    if isinstance(english_label, str) and english_label.strip():
        wikidata_titles.add(normalize_evidence_title(english_label))
    if not movie_titles or not wikidata_titles:
        return True
    return bool(movie_titles & wikidata_titles)


def _language_compatible(language_code: str, labels: list[str]) -> bool:
    accepted = LANGUAGE_LABELS.get(language_code, {language_code.casefold()})
    normalized = {str(label).casefold() for label in labels if str(label).strip()}
    return bool(accepted & normalized)


def _has_language_label(titles: list[dict[str, Any]], language_code: str) -> bool:
    return any(
        isinstance(item, dict) and str(item.get("language") or "").casefold() == language_code
        for item in titles
    )


def _year_from_value(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and len(value) >= 4 and value[:4].isdigit():
        return int(value[:4])
    return None


def _check_manifest_count(errors: list[str], manifest_counts: dict[str, Any], key: str, actual: int) -> None:
    if manifest_counts.get(key) != actual:
        errors.append(f"manifest_count_mismatch:{key}")


def _check_manifest_hashes(errors: list[str], run_dir: Path, output_hashes: dict[str, Any]) -> None:
    for name, expected_hash in output_hashes.items():
        path = run_dir / name
        if not path.exists():
            errors.append(f"manifest_hash_target_missing:{name}")
            continue
        # ponytail: skip the manifest self-hash because embedding the hash mutates the file; upgrade to detached signatures if this must be strict.
        if name == "run_manifest.json":
            continue
        actual_hash = _sha256_path(path)
        if str(expected_hash) != actual_hash:
            errors.append(f"manifest_hash_mismatch:{name}")


def _missing_resolution_record(tmdb_movie_id: str) -> dict[str, Any]:
    return {
        "tmdb_source_movie_id": tmdb_movie_id,
        "match_status": WIKIDATA_ERROR,
        "wikidata_qid": None,
        "english_label": None,
        "titles": [],
        "alternate_titles": [],
        "imdb_id": None,
        "original_languages": [],
        "countries_of_origin": [],
        "directors": [],
        "publication_date": None,
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid json in {path.name}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"json file must contain an object: {path.name}")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid jsonl in {path.name} line {line_number}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"jsonl row must be an object in {path.name} line {line_number}")
        rows.append(payload)
    return rows


def _detect_secrets(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    findings: list[str] = []
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            findings.append(f"secret_pattern_detected:{path.name}")
            break
    return findings


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
