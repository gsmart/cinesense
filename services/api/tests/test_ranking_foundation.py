from app.core.config import Settings
from app.core.ranking import build_ranking_input, compare_rankings, compute_ranking


def make_settings(**overrides) -> Settings:
    return Settings().model_copy(
        update={
            "active_ranking_version": "cine-score-v1",
            "shadow_ranking_version": "disabled",
            "fallback_ranking_version": "cine-score-v1",
            **overrides,
        }
    )


def make_input() -> object:
    return build_ranking_input(
        normalized_query="heat",
        canonical_title="heat",
        release_year=1995,
        requested_year=1995,
        vote_average=8.0,
        vote_count=1000,
        popularity=50.0,
        missing_signals=["critic_consensus"],
        freshness={"audience_reception": "FRESH", "popularity": "FRESH", "critic_consensus": "MISSING"},
        tmdb_source_movie_id="949",
        provider_position=0,
        case_id="heat-1995",
    )


def test_requested_v1_returns_v1_without_fallback():
    result = compute_ranking(make_input(), requested_version="cine-score-v1", settings=make_settings())

    assert result.requested_ranking_version == "cine-score-v1"
    assert result.applied_ranking_version == "cine-score-v1"
    assert result.fallback_used is False
    assert result.fallback_reason is None
    assert result.status == "ok"
    assert result.total == 82.0


def test_requested_v2_falls_back_explicitly_to_v1():
    result = compute_ranking(make_input(), requested_version="cine-score-v2", settings=make_settings())

    assert result.requested_ranking_version == "cine-score-v2"
    assert result.applied_ranking_version == "cine-score-v1"
    assert result.fallback_used is True
    assert result.fallback_reason == "ranking_version_unavailable"
    assert result.status == "fallback_applied"
    assert result.total == 82.0


def test_unknown_requested_version_fails_loudly():
    try:
        compute_ranking(make_input(), requested_version="cine-score-v999", settings=make_settings())
    except ValueError as exc:
        assert str(exc) == "Unsupported ranking version: cine-score-v999"
    else:
        raise AssertionError("expected ValueError")


def test_invalid_active_version_fails_loudly():
    try:
        compute_ranking(make_input(), requested_version=None, settings=make_settings(active_ranking_version="broken"))
    except ValueError as exc:
        assert str(exc) == "Unsupported active ranking version: broken"
    else:
        raise AssertionError("expected ValueError")


def test_disabled_shadow_comparison_returns_controlled_warning():
    comparisons = compare_rankings([make_input()], settings=make_settings())
    comparison = comparisons[0]

    assert comparison.primary_total == 82.0
    assert comparison.shadow_total is None
    assert comparison.score_delta is None
    assert comparison.ordering_delta is None
    assert comparison.warnings == ["shadow_ranking_disabled"]


def test_v2_shadow_comparison_is_explicit_even_before_v2_exists():
    comparisons = compare_rankings([make_input()], settings=make_settings(shadow_ranking_version="cine-score-v2"))
    comparison = comparisons[0]

    assert comparison.shadow_requested_ranking_version == "cine-score-v2"
    assert comparison.shadow_applied_ranking_version == "cine-score-v1"
    assert comparison.shadow_total == 82.0
    assert comparison.score_delta == 0.0
    assert comparison.ordering_delta == 0
    assert comparison.warnings == ["shadow_fallback:ranking_version_unavailable"]
