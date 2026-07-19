from app.cine_score_v2 import (
    CohortSignalSamples,
    ShadowScoreWeights,
    compute_cine_score_v2_shadow,
    empirical_percentile,
)


def assignment_row(
    *,
    tmdb_movie_id: str = "1",
    level: str = "level_1",
    rating: float | None = 0.8,
    vote_log: float | None = 2.0,
    popularity_log: float | None = 1.5,
    entity_status: str = "VALIDATED_EXACT_MATCH",
    review_decision: str | None = None,
) -> dict:
    return {
        "tmdb_movie_id": tmdb_movie_id,
        "level_1_cohort_key": "language=mr|era=2010_2019|genre=unknown_genre",
        "level_2_cohort_key": "language=mr|era=2010_2019",
        "level_3_cohort_key": "language=mr",
        "global_cohort_key": "global=regional_sample",
        "selected_eligible_cohort_key": {
            "level_1": "language=mr|era=2010_2019|genre=unknown_genre",
            "level_2": "language=mr|era=2010_2019",
            "level_3": "language=mr",
            "level_4": "global=regional_sample",
        }.get(level),
        "selected_eligible_cohort_level": level,
        "entity_resolution_status": entity_status,
        "review_decision": review_decision,
        "signal_values": {
            "tmdb_rating_normalized": {"value": rating, "exclusion_reason": None if rating is not None else "missing", "scale": "0-1"},
            "tmdb_vote_count_log1p": {"value": vote_log, "exclusion_reason": None if vote_log is not None else "missing", "scale": None},
            "tmdb_popularity_log1p": {"value": popularity_log, "exclusion_reason": None if popularity_log is not None else "missing", "scale": None},
        },
    }


def cohort_record(*, level: str = "level_1", sample_count: int = 16) -> dict:
    return {"cohort_level": level, "sample_count": sample_count}


def cohort_samples() -> CohortSignalSamples:
    return CohortSignalSamples(
        rating_normalized=(0.4, 0.6, 0.8, 0.8, 0.9),
        vote_count_log1p=(0.5, 1.0, 2.0, 3.0, 4.0),
        popularity_log1p=(0.2, 0.5, 1.5, 2.0, 2.5),
    )


def test_empirical_percentile_and_tie_rule_are_deterministic():
    assert empirical_percentile((0.4, 0.6, 0.8, 0.8, 0.9), 0.8) == 0.6
    assert empirical_percentile((0.4, 0.6, 0.8, 0.8, 0.9), 0.9) == 0.9


def test_invalid_weight_sum_fails():
    try:
        ShadowScoreWeights(quality=0.5, vote_reach=0.2, popularity_reach=0.1, confidence=0.1).validate()
    except ValueError as exc:
        assert "must sum to 1.0" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_shadow_score_computes_quality_reach_confidence_and_total():
    result = compute_cine_score_v2_shadow(
        assignment=assignment_row(),
        cohort_record=cohort_record(),
        cohort_samples=cohort_samples(),
        baseline_hash="hash",
        provisional_status="APPROVED_FOR_SHADOW",
        activation_eligible=False,
    )

    assert result["quality_component"] == 0.6
    assert result["vote_reach_component"] == 0.5
    assert result["popularity_reach_component"] == 0.5
    assert 0.0 <= result["confidence_component"] <= 1.0
    assert 0.0 <= result["raw_total"] <= 1.0
    assert result["display_total"] == round(result["raw_total"] * 100.0, 2)


def test_missing_quality_keeps_null_and_reweights_active_components():
    result = compute_cine_score_v2_shadow(
        assignment=assignment_row(rating=None),
        cohort_record=cohort_record(),
        cohort_samples=cohort_samples(),
        baseline_hash="hash",
        provisional_status="PROVISIONAL_SHADOW_ONLY",
        activation_eligible=False,
    )

    assert result["quality_component"] is None
    assert "quality" in result["missing_components"]
    assert result["active_weights"] == {
        "confidence": 0.25,
        "popularity_reach": 0.25,
        "vote_reach": 0.5,
    }
    assert "MISSING_QUALITY_SIGNAL" in result["diagnostic_flags"]


def test_all_intrinsic_missing_produces_no_score_without_zero_imputation():
    result = compute_cine_score_v2_shadow(
        assignment=assignment_row(rating=None, vote_log=None, popularity_log=None),
        cohort_record=cohort_record(),
        cohort_samples=cohort_samples(),
        baseline_hash="hash",
        provisional_status="PROVISIONAL_SHADOW_ONLY",
        activation_eligible=False,
    )

    assert result["raw_total"] is None
    assert result["display_total"] is None
    assert "no_intrinsic_v2_signals" in result["warnings"]


def test_fallback_level_changes_confidence_but_not_quality():
    level_1 = compute_cine_score_v2_shadow(
        assignment=assignment_row(level="level_1"),
        cohort_record=cohort_record(level="level_1", sample_count=16),
        cohort_samples=cohort_samples(),
        baseline_hash="hash",
        provisional_status="APPROVED_FOR_SHADOW",
        activation_eligible=False,
    )
    level_4 = compute_cine_score_v2_shadow(
        assignment=assignment_row(level="level_4"),
        cohort_record=cohort_record(level="level_4", sample_count=100),
        cohort_samples=cohort_samples(),
        baseline_hash="hash",
        provisional_status="APPROVED_FOR_SHADOW",
        activation_eligible=False,
    )

    assert level_1["quality_component"] == level_4["quality_component"]
    assert level_1["confidence_component"] > level_4["confidence_component"]


def test_no_tmdb_native_penalty_for_missing_or_ambiguous_wikidata():
    no_match = compute_cine_score_v2_shadow(
        assignment=assignment_row(entity_status="NO_MATCH"),
        cohort_record=cohort_record(),
        cohort_samples=cohort_samples(),
        baseline_hash="hash",
        provisional_status="BLOCKED_FROM_DATA_APPROVAL",
        activation_eligible=False,
    )
    ambiguous = compute_cine_score_v2_shadow(
        assignment=assignment_row(entity_status="AMBIGUOUS_REVIEW_REQUIRED"),
        cohort_record=cohort_record(),
        cohort_samples=cohort_samples(),
        baseline_hash="hash",
        provisional_status="BLOCKED_FROM_DATA_APPROVAL",
        activation_eligible=False,
    )

    assert no_match["quality_component"] == 0.6
    assert ambiguous["quality_component"] == 0.6
    assert no_match["confidence_component"] == ambiguous["confidence_component"] == 0.86
