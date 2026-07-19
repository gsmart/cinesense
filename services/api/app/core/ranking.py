from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.config import Settings
from app.core.scoring import compute_cine_score_v1

ACTIVE_RANKING_VERSION = "cine-score-v1"
EXPERIMENTAL_RANKING_VERSION = "cine-score-v2"
DISABLED_RANKING_VERSION = "disabled"
SUPPORTED_RANKING_VERSIONS = {ACTIVE_RANKING_VERSION}
KNOWN_RANKING_VERSIONS = SUPPORTED_RANKING_VERSIONS | {EXPERIMENTAL_RANKING_VERSION}
RankingStatus = Literal["ok", "fallback_applied"]


@dataclass(frozen=True)
class RankingInput:
    normalized_query: str
    canonical_title: str
    release_year: int | None
    requested_year: int | None
    vote_average: float | None
    vote_count: int | None
    popularity: float | None
    missing_signals: tuple[str, ...]
    freshness: dict[str, str]
    seed_relevance: float | None = None
    tmdb_source_movie_id: str | None = None
    provider_position: int | None = None
    case_id: str | None = None


@dataclass(frozen=True)
class RankingComputation:
    requested_ranking_version: str
    applied_ranking_version: str
    fallback_used: bool
    fallback_reason: str | None
    status: RankingStatus
    total: float
    components: dict[str, float | None]
    missing_signals: list[str]

    def public_score(self) -> dict[str, object]:
        return {
            "version": self.applied_ranking_version,
            "total": self.total,
            "components": self.components,
            "missing_signals": self.missing_signals,
        }


@dataclass(frozen=True)
class RankingComparison:
    identifier: str
    provider_position: int | None
    requested_ranking_version: str
    applied_ranking_version: str
    shadow_requested_ranking_version: str | None
    shadow_applied_ranking_version: str | None
    primary_total: float
    shadow_total: float | None
    score_delta: float | None
    primary_rank: int
    shadow_rank: int | None
    ordering_delta: int | None
    missing_signals: list[str]
    warnings: list[str]


def build_ranking_input(
    *,
    normalized_query: str,
    canonical_title: str,
    release_year: int | None,
    requested_year: int | None,
    vote_average: float | None,
    vote_count: int | None,
    popularity: float | None,
    missing_signals: list[str],
    freshness: dict[str, str] | None = None,
    seed_relevance: float | None = None,
    tmdb_source_movie_id: str | None = None,
    provider_position: int | None = None,
    case_id: str | None = None,
) -> RankingInput:
    return RankingInput(
        normalized_query=normalized_query,
        canonical_title=canonical_title,
        release_year=release_year,
        requested_year=requested_year,
        vote_average=vote_average,
        vote_count=vote_count,
        popularity=popularity,
        missing_signals=tuple(missing_signals),
        freshness=dict(freshness or {}),
        seed_relevance=seed_relevance,
        tmdb_source_movie_id=tmdb_source_movie_id,
        provider_position=provider_position,
        case_id=case_id,
    )


def compute_ranking(
    ranking_input: RankingInput,
    *,
    requested_version: str | None,
    settings: Settings,
) -> RankingComputation:
    _validate_ranking_settings(settings)
    target_version = requested_version or settings.active_ranking_version

    if target_version == ACTIVE_RANKING_VERSION:
        return _compute_v1_result(
            ranking_input,
            requested_ranking_version=target_version,
            fallback_used=False,
            fallback_reason=None,
            status="ok",
        )

    if target_version == EXPERIMENTAL_RANKING_VERSION:
        if settings.fallback_ranking_version != ACTIVE_RANKING_VERSION:
            raise ValueError("Experimental ranking requests require cine-score-v1 fallback")
        return _compute_v1_result(
            ranking_input,
            requested_ranking_version=target_version,
            fallback_used=True,
            fallback_reason="ranking_version_unavailable",
            status="fallback_applied",
        )

    raise ValueError(f"Unsupported ranking version: {target_version}")


def compute_shadow_ranking(
    ranking_input: RankingInput,
    *,
    settings: Settings,
) -> RankingComputation | None:
    shadow_version = settings.shadow_ranking_version
    if not shadow_version or shadow_version == DISABLED_RANKING_VERSION:
        return None
    return compute_ranking(ranking_input, requested_version=shadow_version, settings=settings)


def compare_rankings(
    ranking_inputs: list[RankingInput],
    *,
    settings: Settings,
) -> list[RankingComparison]:
    primary = [
        compute_ranking(ranking_input, requested_version=settings.active_ranking_version, settings=settings)
        for ranking_input in ranking_inputs
    ]
    shadow = [compute_shadow_ranking(ranking_input, settings=settings) for ranking_input in ranking_inputs]

    primary_order = _ordered_indices(ranking_inputs, primary)
    shadow_order = _ordered_indices(ranking_inputs, shadow) if any(item is not None for item in shadow) else None

    comparisons: list[RankingComparison] = []
    for index, ranking_input in enumerate(ranking_inputs):
        primary_result = primary[index]
        shadow_result = shadow[index]
        warnings = []
        if shadow_result is None:
            warnings.append("shadow_ranking_disabled")
        elif shadow_result.fallback_used:
            warnings.append(f"shadow_fallback:{shadow_result.fallback_reason}")

        identifier = ranking_input.case_id or ranking_input.tmdb_source_movie_id or ranking_input.canonical_title
        shadow_rank = None
        ordering_delta = None
        shadow_total = None
        shadow_requested_version = None
        shadow_applied_version = None
        score_delta = None
        if shadow_result is not None and shadow_order is not None:
            shadow_rank = shadow_order[index]
            ordering_delta = primary_order[index] - shadow_rank
            shadow_total = shadow_result.total
            shadow_requested_version = shadow_result.requested_ranking_version
            shadow_applied_version = shadow_result.applied_ranking_version
            score_delta = round(shadow_result.total - primary_result.total, 2)

        comparisons.append(
            RankingComparison(
                identifier=identifier,
                provider_position=ranking_input.provider_position,
                requested_ranking_version=primary_result.requested_ranking_version,
                applied_ranking_version=primary_result.applied_ranking_version,
                shadow_requested_ranking_version=shadow_requested_version,
                shadow_applied_ranking_version=shadow_applied_version,
                primary_total=primary_result.total,
                shadow_total=shadow_total,
                score_delta=score_delta,
                primary_rank=primary_order[index],
                shadow_rank=shadow_rank,
                ordering_delta=ordering_delta,
                missing_signals=list(primary_result.missing_signals),
                warnings=warnings,
            )
        )
    return comparisons


def _compute_v1_result(
    ranking_input: RankingInput,
    *,
    requested_ranking_version: str,
    fallback_used: bool,
    fallback_reason: str | None,
    status: RankingStatus,
) -> RankingComputation:
    score = compute_cine_score_v1(
        normalized_query=ranking_input.normalized_query,
        canonical_title=ranking_input.canonical_title,
        release_year=ranking_input.release_year,
        requested_year=ranking_input.requested_year,
        vote_average=ranking_input.vote_average,
        vote_count=ranking_input.vote_count,
        popularity=ranking_input.popularity,
        missing_signals=list(ranking_input.missing_signals),
        seed_relevance=ranking_input.seed_relevance,
    )
    return RankingComputation(
        requested_ranking_version=requested_ranking_version,
        applied_ranking_version=score["version"],
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        status=status,
        total=score["total"],
        components=score["components"],
        missing_signals=score["missing_signals"],
    )


def _ordered_indices(
    ranking_inputs: list[RankingInput],
    results: list[RankingComputation | None],
) -> dict[int, int]:
    sortable = []
    for index, (ranking_input, result) in enumerate(zip(ranking_inputs, results, strict=True)):
        if result is None:
            continue
        sortable.append((index, result, ranking_input))
    sortable.sort(
        key=lambda item: (
            -item[1].total,
            item[2].provider_position if item[2].provider_position is not None else 10**9,
            item[2].tmdb_source_movie_id or item[2].case_id or item[2].canonical_title,
        )
    )
    return {index: position for position, (index, _result, _input) in enumerate(sortable, start=1)}


def _validate_ranking_settings(settings: Settings) -> None:
    active = settings.active_ranking_version
    fallback = settings.fallback_ranking_version
    shadow = settings.shadow_ranking_version

    if active not in KNOWN_RANKING_VERSIONS:
        raise ValueError(f"Unsupported active ranking version: {active}")
    if fallback not in KNOWN_RANKING_VERSIONS:
        raise ValueError(f"Unsupported fallback ranking version: {fallback}")
    if shadow and shadow != DISABLED_RANKING_VERSION and shadow not in KNOWN_RANKING_VERSIONS:
        raise ValueError(f"Unsupported shadow ranking version: {shadow}")
