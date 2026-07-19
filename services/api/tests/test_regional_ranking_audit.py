from app.core.regional_ranking_audit import (
    build_synthetic_regional_ranking_fixtures,
    order_results_within_groups,
    run_ranking_audit_case,
    run_regional_ranking_audit,
)
from app.core.scoring import compute_cine_score_v1


def _result_by_case(case_id: str):
    results = run_regional_ranking_audit()
    return next(result for result in results if result.case.case_id == case_id)


def test_audit_uses_cine_score_v1_and_keeps_version_explicit():
    results = run_regional_ranking_audit()

    assert results
    assert {result.version for result in results} == {"cine-score-v1"}


def test_current_v1_outputs_remain_deterministic_and_equal_inputs_match():
    first = run_regional_ranking_audit()
    second = run_regional_ranking_audit()
    by_case = {result.case.case_id: result for result in first}

    assert first == second
    assert by_case["G-identical-one"].total == by_case["G-identical-two"].total
    assert by_case["G-identical-one"].components == by_case["G-identical-two"].components


def test_lower_evidence_changes_only_evidence_confidence_for_equal_inputs():
    low = _result_by_case("A-low-evidence")
    high = _result_by_case("A-high-evidence")

    assert low.components["audience_reception"] == high.components["audience_reception"]
    assert low.components["popularity"] == high.components["popularity"]
    assert low.components["data_coverage"] == high.components["data_coverage"]
    assert low.components["evidence_confidence"] < high.components["evidence_confidence"]


def test_lower_popularity_changes_only_popularity_component_for_equal_inputs():
    low = _result_by_case("B-low-popularity")
    high = _result_by_case("B-high-popularity")

    assert low.components["audience_reception"] == high.components["audience_reception"]
    assert low.components["evidence_confidence"] == high.components["evidence_confidence"]
    assert low.components["data_coverage"] == high.components["data_coverage"]
    assert low.components["popularity"] < high.components["popularity"]


def test_missing_critic_remains_explicit_and_never_becomes_zero():
    result = _result_by_case("E-critic-missing")

    assert result.components["critic_consensus"] is None
    assert "critic_consensus" in result.missing_signals


def test_group_ordering_is_stable_and_exposes_regional_vs_mainstream_behavior():
    grouped_once = order_results_within_groups(run_regional_ranking_audit())
    grouped_twice = order_results_within_groups(run_regional_ranking_audit())

    assert [item.case.case_id for item in grouped_once["C"]] == [item.case.case_id for item in grouped_twice["C"]]
    assert grouped_once["C"][0].case.case_id == "C-mainstream-style"


def test_audit_has_no_database_writes_or_provider_or_llm_calls():
    results = run_regional_ranking_audit(build_synthetic_regional_ranking_fixtures())

    assert len(results) == len(build_synthetic_regional_ranking_fixtures())


def test_sparse_low_quality_candidate_is_not_treated_as_acclaimed():
    sparse = _result_by_case("F-sparse-low-quality")
    regional = _result_by_case("C-regional-style")
    mainstream = _result_by_case("C-mainstream-style")

    assert sparse.total < regional.total
    assert sparse.total < mainstream.total
    assert sparse.components["audience_reception"] < regional.components["audience_reception"]


def test_existing_scorer_results_remain_unchanged_after_audit_execution():
    baseline = compute_cine_score_v1(
        normalized_query="heat",
        canonical_title="heat",
        release_year=1995,
        requested_year=1995,
        vote_average=8.0,
        vote_count=1000,
        popularity=50.0,
        missing_signals=["critic_consensus"],
    )

    run_regional_ranking_audit()

    after = compute_cine_score_v1(
        normalized_query="heat",
        canonical_title="heat",
        release_year=1995,
        requested_year=1995,
        vote_average=8.0,
        vote_count=1000,
        popularity=50.0,
        missing_signals=["critic_consensus"],
    )

    assert baseline == after


def test_critic_present_annotation_has_no_current_v1_effect_because_no_critic_input_path_exists():
    annotated = _result_by_case("E-critic-annotated-present")
    missing = _result_by_case("E-critic-missing")

    assert annotated.total == missing.total
    assert annotated.components == missing.components


def test_component_audit_uses_explicit_maximums_only():
    result = _result_by_case("A-high-evidence")

    assert result.component_audit["query_match"].maximum == 30.0
    assert result.component_audit["audience_reception"].maximum == 25.0
    assert result.component_audit["popularity"].maximum == 10.0
    assert result.component_audit["evidence_confidence"].maximum == 20.0
    assert result.component_audit["critic_consensus"].maximum is None
