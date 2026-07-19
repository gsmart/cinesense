from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.regional_cohort_baselines import BASELINE_SCHEMA_VERSION, DEFAULT_LEVEL_THRESHOLDS

SCORE_VERSION = "cine-score-v2-shadow-1"
COMPONENT_PRECISION = 6
DISPLAY_PRECISION = 2
SUPPORTED_SIGNAL_NAMES = (
    "tmdb_rating_normalized",
    "tmdb_vote_count_log1p",
    "tmdb_popularity_log1p",
)
SPECIFICITY_CONFIDENCE = {
    "level_1": 1.0,
    "level_2": 0.92,
    "level_3": 0.84,
    "level_4": 0.76,
    "unavailable": 0.0,
}


@dataclass(frozen=True)
class ShadowScoreWeights:
    quality: float = 0.60
    vote_reach: float = 0.20
    popularity_reach: float = 0.10
    confidence: float = 0.10

    def as_dict(self) -> dict[str, float]:
        return {
            "quality": self.quality,
            "vote_reach": self.vote_reach,
            "popularity_reach": self.popularity_reach,
            "confidence": self.confidence,
        }

    def validate(self) -> None:
        total = self.quality + self.vote_reach + self.popularity_reach + self.confidence
        if any(value < 0 for value in self.as_dict().values()):
            raise ValueError("shadow score weights must be non-negative")
        if not math.isclose(total, 1.0, abs_tol=1e-9):
            raise ValueError(f"shadow score weights must sum to 1.0, got {total}")


@dataclass(frozen=True)
class CohortSignalSamples:
    rating_normalized: tuple[float, ...]
    vote_count_log1p: tuple[float, ...]
    popularity_log1p: tuple[float, ...]


def load_baseline_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def empirical_percentile(sorted_values: tuple[float, ...], candidate: float) -> float | None:
    if not sorted_values:
        return None
    below = 0
    equal = 0
    for value in sorted_values:
        if value < candidate:
            below += 1
        elif value == candidate:
            equal += 1
    return _round_component((below + 0.5 * equal) / len(sorted_values))


def compute_cine_score_v2_shadow(
    *,
    assignment: dict[str, Any],
    cohort_record: dict[str, Any] | None,
    cohort_samples: CohortSignalSamples | None,
    baseline_hash: str,
    provisional_status: str,
    activation_eligible: bool,
    warnings: list[str] | None = None,
    weights: ShadowScoreWeights | None = None,
) -> dict[str, Any]:
    weights = weights or ShadowScoreWeights()
    weights.validate()
    warnings = sorted(set(warnings or []))

    selected_level = str(assignment.get("selected_eligible_cohort_level") or "unavailable")
    selected_key = assignment.get("selected_eligible_cohort_key")
    sample_count = int(cohort_record["sample_count"]) if cohort_record else 0
    fallback_path = [
        assignment.get("level_1_cohort_key"),
        assignment.get("level_2_cohort_key"),
        assignment.get("level_3_cohort_key"),
        assignment.get("global_cohort_key"),
        "unavailable",
    ]
    missing_components: list[str] = []
    diagnostic_flags: list[str] = []

    if provisional_status != "APPROVED_FOR_SHADOW":
        diagnostic_flags.append("PROVISIONAL_BASELINE")
    if selected_level == "level_3":
        diagnostic_flags.append("LANGUAGE_FALLBACK_USED")
    if selected_level == "level_4":
        diagnostic_flags.append("GLOBAL_FALLBACK_USED")
    if selected_level == "unavailable":
        warnings.append("unavailable_selected_cohort")

    quality = _quality_component(assignment, cohort_samples)
    vote_reach = _reach_component(assignment, cohort_samples, signal_name="tmdb_vote_count_log1p")
    popularity_reach = _reach_component(assignment, cohort_samples, signal_name="tmdb_popularity_log1p")
    confidence = _confidence_component(
        assignment=assignment,
        cohort_record=cohort_record,
        selected_level=selected_level,
        vote_reach=vote_reach,
    )

    if quality is None:
        missing_components.append("quality")
        diagnostic_flags.append("MISSING_QUALITY_SIGNAL")
    if vote_reach is None:
        missing_components.append("vote_reach")
    if popularity_reach is None:
        missing_components.append("popularity_reach")
    if confidence is None:
        missing_components.append("confidence")
    elif confidence < 0.5:
        diagnostic_flags.append("LOW_CONFIDENCE")

    active_weights = _active_weights(
        weights=weights,
        quality=quality,
        vote_reach=vote_reach,
        popularity_reach=popularity_reach,
        confidence=confidence,
    )
    intrinsic_available = any(value is not None for value in (quality, vote_reach, popularity_reach))
    raw_total = None
    display_total = None
    if intrinsic_available and active_weights:
        raw_total = sum(
            value * active_weights[name]
            for name, value in {
                "quality": quality,
                "vote_reach": vote_reach,
                "popularity_reach": popularity_reach,
                "confidence": confidence,
            }.items()
            if value is not None and name in active_weights
        )
        raw_total = _round_component(raw_total)
        display_total = round(raw_total * 100.0, DISPLAY_PRECISION)
    else:
        warnings.append("no_intrinsic_v2_signals")

    return {
        "score_version": SCORE_VERSION,
        "baseline_version": BASELINE_SCHEMA_VERSION,
        "baseline_hash": baseline_hash,
        "tmdb_movie_id": assignment["tmdb_movie_id"],
        "cohort_key": selected_key,
        "cohort_level": selected_level,
        "cohort_sample_size": sample_count,
        "cohort_fallback_path": fallback_path,
        "quality_component": quality,
        "vote_reach_component": vote_reach,
        "popularity_reach_component": popularity_reach,
        "confidence_component": confidence,
        "contextual_relevance": None,
        "original_weights": {name: _round_component(value) for name, value in weights.as_dict().items()},
        "active_weights": active_weights,
        "missing_components": sorted(set(missing_components)),
        "warnings": sorted(set(warnings)),
        "diagnostic_flags": sorted(set(diagnostic_flags)),
        "raw_total": raw_total,
        "display_total": display_total,
        "activation_eligible": activation_eligible,
        "provisional_status": provisional_status,
    }


def _quality_component(assignment: dict[str, Any], cohort_samples: CohortSignalSamples | None) -> float | None:
    signal_entry = assignment["signal_values"]["tmdb_rating_normalized"]
    if signal_entry["value"] is None or cohort_samples is None:
        return None
    return empirical_percentile(cohort_samples.rating_normalized, float(signal_entry["value"]))


def _reach_component(
    assignment: dict[str, Any],
    cohort_samples: CohortSignalSamples | None,
    *,
    signal_name: str,
) -> float | None:
    signal_entry = assignment["signal_values"][signal_name]
    if signal_entry["value"] is None or cohort_samples is None:
        return None
    sample_values = {
        "tmdb_vote_count_log1p": cohort_samples.vote_count_log1p,
        "tmdb_popularity_log1p": cohort_samples.popularity_log1p,
    }[signal_name]
    return empirical_percentile(sample_values, float(signal_entry["value"]))


def _confidence_component(
    *,
    assignment: dict[str, Any],
    cohort_record: dict[str, Any] | None,
    selected_level: str,
    vote_reach: float | None,
) -> float | None:
    if cohort_record is None:
        return None
    sample_count = int(cohort_record["sample_count"])
    threshold = DEFAULT_LEVEL_THRESHOLDS.get(selected_level, DEFAULT_LEVEL_THRESHOLDS["level_4"])
    cohort_sample_confidence = min(1.0, sample_count / max(1, threshold * 2))
    signal_completeness = (
        sum(
            1
            for name in ("tmdb_rating_normalized", "tmdb_vote_count_log1p", "tmdb_popularity_log1p")
            if assignment["signal_values"][name]["value"] is not None
        )
        / 3.0
    )
    identity_confidence = _identity_confidence(
        entity_status=str(assignment.get("entity_resolution_status") or ""),
        review_decision=assignment.get("review_decision"),
    )
    vote_evidence_confidence = vote_reach
    specificity_confidence = SPECIFICITY_CONFIDENCE.get(selected_level, 0.0)
    parts = [
        cohort_sample_confidence,
        signal_completeness,
        identity_confidence,
        specificity_confidence,
    ]
    if vote_evidence_confidence is not None:
        parts.append(vote_evidence_confidence)
    if not parts:
        return None
    return _round_component(sum(parts) / len(parts))


def _identity_confidence(*, entity_status: str, review_decision: Any) -> float:
    decision = str(review_decision or "")
    if decision == "CONFIRMED":
        return 1.0
    if entity_status == "VALIDATED_EXACT_MATCH":
        return 1.0
    if entity_status == "EXACT_MATCH_WITH_WARNINGS":
        return 0.9
    if entity_status == "SOURCE_ERROR":
        return 0.85
    return 1.0


def _active_weights(
    *,
    weights: ShadowScoreWeights,
    quality: float | None,
    vote_reach: float | None,
    popularity_reach: float | None,
    confidence: float | None,
) -> dict[str, float]:
    candidates = {
        "quality": (quality, weights.quality),
        "vote_reach": (vote_reach, weights.vote_reach),
        "popularity_reach": (popularity_reach, weights.popularity_reach),
        "confidence": (confidence, weights.confidence),
    }
    present_weight = sum(weight for value, weight in candidates.values() if value is not None)
    if present_weight <= 0:
        return {}
    return {
        name: _round_component(weight / present_weight)
        for name, (value, weight) in candidates.items()
        if value is not None
    }


def _round_component(value: float) -> float:
    return round(float(value), COMPONENT_PRECISION)
