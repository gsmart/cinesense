import math
from typing import Any


def clamp(value: float, floor: float = 0.0, ceiling: float = 1.0) -> float:
    return max(floor, min(ceiling, value))


def compute_cine_score_v1(
    *,
    normalized_query: str,
    canonical_title: str,
    release_year: int | None,
    requested_year: int | None,
    vote_average: float | None,
    vote_count: int | None,
    popularity: float | None,
    missing_signals: list[str],
    seed_relevance: float | None = None,
) -> dict[str, Any]:
    if seed_relevance is not None:
        query_match = round(30.0 * clamp(seed_relevance), 2)
    else:
        title_match = 1.0 if normalized_query == canonical_title else 0.85
        year_bonus = 1.0 if requested_year and requested_year == release_year else 0.8
        query_match = round(30.0 * title_match * year_bonus, 2)

    audience_reception = None
    if vote_average is not None:
        audience_reception = round(clamp(vote_average / 10.0) * 25.0, 2)

    popularity_component = None
    if popularity is not None:
        popularity_component = round(clamp(popularity / 100.0) * 10.0, 2)

    evidence_confidence = None
    if vote_count is not None:
        evidence_confidence = round(clamp(math.log10(vote_count + 1) / 4.0) * 20.0, 2)

    critic_consensus = None
    intended_signals = 5
    present_signals = 1
    for candidate in (audience_reception, popularity_component, evidence_confidence):
        if candidate is not None:
            present_signals += 1
    coverage = round((present_signals / intended_signals) * 15.0, 2)

    total = query_match + coverage
    for candidate in (audience_reception, popularity_component, evidence_confidence, critic_consensus):
        if candidate is not None:
            total += candidate

    return {
        "version": "cine-score-v1",
        "total": round(total, 2),
        "components": {
            "query_match": query_match,
            "audience_reception": audience_reception,
            "critic_consensus": critic_consensus,
            "popularity": popularity_component,
            "evidence_confidence": evidence_confidence,
            "data_coverage": coverage,
        },
        "missing_signals": missing_signals,
    }
