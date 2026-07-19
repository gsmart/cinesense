from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.scoring import compute_cine_score_v1
from app.models.movie import Movie, Observation

FixtureClassification = Literal["synthetic", "captured_local_observation"]

COMPONENT_MAXIMUMS = {
    "query_match": 30.0,
    "audience_reception": 25.0,
    "popularity": 10.0,
    "evidence_confidence": 20.0,
    "data_coverage": 15.0,
}


@dataclass(frozen=True)
class RankingAuditCase:
    case_id: str
    group_id: str
    display_label: str
    language_or_category: str
    original_language: str | None
    release_year: int | None
    normalized_query: str
    canonical_title: str
    requested_year: int | None
    vote_average: float | None
    rating_scale: str | None
    vote_count: int | None
    popularity: float | None
    critic_consensus_state: Literal["missing", "present"]
    expected_source_identity: str
    fixture_classification: FixtureClassification
    provenance_notes: str | None = None


@dataclass(frozen=True)
class ComponentAudit:
    achieved: float | None
    maximum: float | None
    difference_from_maximum: float | None


@dataclass(frozen=True)
class RankingAuditResult:
    case: RankingAuditCase
    version: str
    total: float
    components: dict[str, float | None]
    missing_signals: list[str]
    raw_audience_value: float | None
    evidence_count: int | None
    raw_popularity: float | None
    component_audit: dict[str, ComponentAudit]
    critic_state: str


@dataclass(frozen=True)
class CapturedAuditExport:
    cases: list[RankingAuditCase]
    unavailable_titles: list[str]


def _component_audit(components: dict[str, float | None]) -> dict[str, ComponentAudit]:
    audited: dict[str, ComponentAudit] = {}
    for name, value in components.items():
        maximum = COMPONENT_MAXIMUMS.get(name)
        audited[name] = ComponentAudit(
            achieved=value,
            maximum=maximum,
            difference_from_maximum=round(maximum - value, 2) if maximum is not None and value is not None else None,
        )
    return audited


def run_ranking_audit_case(case: RankingAuditCase) -> RankingAuditResult:
    missing_signals = ["critic_consensus"]
    if case.vote_average is None:
        missing_signals.append("audience_reception")
    if case.popularity is None:
        missing_signals.append("popularity")

    score = compute_cine_score_v1(
        normalized_query=case.normalized_query,
        canonical_title=case.canonical_title,
        release_year=case.release_year,
        requested_year=case.requested_year,
        vote_average=case.vote_average,
        vote_count=case.vote_count,
        popularity=case.popularity,
        missing_signals=missing_signals,
        seed_relevance=1.0,
    )
    components = score["components"]
    return RankingAuditResult(
        case=case,
        version=score["version"],
        total=score["total"],
        components=components,
        missing_signals=score["missing_signals"],
        raw_audience_value=case.vote_average,
        evidence_count=case.vote_count,
        raw_popularity=case.popularity,
        component_audit=_component_audit(components),
        critic_state=case.critic_consensus_state,
    )


def build_synthetic_regional_ranking_fixtures() -> list[RankingAuditCase]:
    return [
        RankingAuditCase(
            case_id="A-low-evidence",
            group_id="A",
            display_label="Equal quality, low evidence",
            language_or_category="synthetic",
            original_language="en",
            release_year=2018,
            normalized_query="equal quality case",
            canonical_title="equal quality case",
            requested_year=2018,
            vote_average=8.0,
            rating_scale="0-10",
            vote_count=50,
            popularity=20.0,
            critic_consensus_state="missing",
            expected_source_identity="tmdb",
            fixture_classification="synthetic",
            provenance_notes="Same rating and popularity as A-high-evidence; only evidence volume changes.",
        ),
        RankingAuditCase(
            case_id="A-high-evidence",
            group_id="A",
            display_label="Equal quality, high evidence",
            language_or_category="synthetic",
            original_language="en",
            release_year=2018,
            normalized_query="equal quality case",
            canonical_title="equal quality case",
            requested_year=2018,
            vote_average=8.0,
            rating_scale="0-10",
            vote_count=50000,
            popularity=20.0,
            critic_consensus_state="missing",
            expected_source_identity="tmdb",
            fixture_classification="synthetic",
            provenance_notes="Same rating and popularity as A-low-evidence; only evidence volume changes.",
        ),
        RankingAuditCase(
            case_id="B-low-popularity",
            group_id="B",
            display_label="Equal quality, low popularity",
            language_or_category="synthetic",
            original_language="en",
            release_year=2020,
            normalized_query="popularity contrast",
            canonical_title="popularity contrast",
            requested_year=2020,
            vote_average=8.0,
            rating_scale="0-10",
            vote_count=3000,
            popularity=3.0,
            critic_consensus_state="missing",
            expected_source_identity="tmdb",
            fixture_classification="synthetic",
            provenance_notes="Same rating and evidence as B-high-popularity; only popularity changes.",
        ),
        RankingAuditCase(
            case_id="B-high-popularity",
            group_id="B",
            display_label="Equal quality, high popularity",
            language_or_category="synthetic",
            original_language="en",
            release_year=2020,
            normalized_query="popularity contrast",
            canonical_title="popularity contrast",
            requested_year=2020,
            vote_average=8.0,
            rating_scale="0-10",
            vote_count=3000,
            popularity=80.0,
            critic_consensus_state="missing",
            expected_source_identity="tmdb",
            fixture_classification="synthetic",
            provenance_notes="Same rating and evidence as B-low-popularity; only popularity changes.",
        ),
        RankingAuditCase(
            case_id="C-regional-style",
            group_id="C",
            display_label="Regional-style lower-volume candidate",
            language_or_category="regional-vs-mainstream",
            original_language="mr",
            release_year=2016,
            normalized_query="regional comparison",
            canonical_title="regional comparison",
            requested_year=2016,
            vote_average=8.9,
            rating_scale="0-10",
            vote_count=250,
            popularity=4.0,
            critic_consensus_state="missing",
            expected_source_identity="tmdb",
            fixture_classification="synthetic",
            provenance_notes="Higher audience rating, lower evidence and popularity than C-mainstream-style.",
        ),
        RankingAuditCase(
            case_id="C-mainstream-style",
            group_id="C",
            display_label="Mainstream-style higher-volume candidate",
            language_or_category="regional-vs-mainstream",
            original_language="en",
            release_year=2016,
            normalized_query="regional comparison",
            canonical_title="regional comparison",
            requested_year=2016,
            vote_average=7.8,
            rating_scale="0-10",
            vote_count=25000,
            popularity=85.0,
            critic_consensus_state="missing",
            expected_source_identity="tmdb",
            fixture_classification="synthetic",
            provenance_notes="Lower audience rating, much higher evidence and popularity than C-regional-style.",
        ),
        RankingAuditCase(
            case_id="D-older-acclaimed",
            group_id="D",
            display_label="Older acclaimed candidate",
            language_or_category="older-vs-trending",
            original_language="ja",
            release_year=1985,
            normalized_query="older versus trending",
            canonical_title="older versus trending",
            requested_year=1985,
            vote_average=8.7,
            rating_scale="0-10",
            vote_count=8000,
            popularity=3.0,
            critic_consensus_state="missing",
            expected_source_identity="tmdb",
            fixture_classification="synthetic",
            provenance_notes="Similar audience quality to D-currently-trending but much lower current popularity.",
        ),
        RankingAuditCase(
            case_id="D-currently-trending",
            group_id="D",
            display_label="Currently trending candidate",
            language_or_category="older-vs-trending",
            original_language="en",
            release_year=2025,
            normalized_query="older versus trending",
            canonical_title="older versus trending",
            requested_year=2025,
            vote_average=8.6,
            rating_scale="0-10",
            vote_count=8000,
            popularity=70.0,
            critic_consensus_state="missing",
            expected_source_identity="tmdb",
            fixture_classification="synthetic",
            provenance_notes="Similar audience quality to D-older-acclaimed but much higher current popularity.",
        ),
        RankingAuditCase(
            case_id="E-critic-annotated-present",
            group_id="E",
            display_label="Critic annotated as present",
            language_or_category="critic-gap",
            original_language="en",
            release_year=2019,
            normalized_query="critic comparison",
            canonical_title="critic comparison",
            requested_year=2019,
            vote_average=8.2,
            rating_scale="0-10",
            vote_count=5000,
            popularity=40.0,
            critic_consensus_state="present",
            expected_source_identity="licensed-critic-source",
            fixture_classification="synthetic",
            provenance_notes="Synthetic metadata only. v1 has no critic input path, so the scorer cannot consume this signal.",
        ),
        RankingAuditCase(
            case_id="E-critic-missing",
            group_id="E",
            display_label="Critic explicitly missing",
            language_or_category="critic-gap",
            original_language="en",
            release_year=2019,
            normalized_query="critic comparison",
            canonical_title="critic comparison",
            requested_year=2019,
            vote_average=8.2,
            rating_scale="0-10",
            vote_count=5000,
            popularity=40.0,
            critic_consensus_state="missing",
            expected_source_identity="tmdb",
            fixture_classification="synthetic",
            provenance_notes="Otherwise identical to E-critic-annotated-present.",
        ),
        RankingAuditCase(
            case_id="F-sparse-low-quality",
            group_id="F",
            display_label="Sparse low-quality candidate",
            language_or_category="guardrail",
            original_language="ta",
            release_year=2014,
            normalized_query="guardrail case",
            canonical_title="guardrail case",
            requested_year=2014,
            vote_average=4.2,
            rating_scale="0-10",
            vote_count=9,
            popularity=0.6,
            critic_consensus_state="missing",
            expected_source_identity="tmdb",
            fixture_classification="synthetic",
            provenance_notes="Low quality and low evidence guardrail case.",
        ),
        RankingAuditCase(
            case_id="G-identical-one",
            group_id="G",
            display_label="Identical baseline one",
            language_or_category="determinism-check",
            original_language="en",
            release_year=2010,
            normalized_query="same baseline",
            canonical_title="same baseline",
            requested_year=2010,
            vote_average=7.5,
            rating_scale="0-10",
            vote_count=1200,
            popularity=25.0,
            critic_consensus_state="missing",
            expected_source_identity="tmdb",
            fixture_classification="synthetic",
        ),
        RankingAuditCase(
            case_id="G-identical-two",
            group_id="G",
            display_label="Identical baseline two",
            language_or_category="determinism-check",
            original_language="en",
            release_year=2010,
            normalized_query="same baseline",
            canonical_title="same baseline",
            requested_year=2010,
            vote_average=7.5,
            rating_scale="0-10",
            vote_count=1200,
            popularity=25.0,
            critic_consensus_state="missing",
            expected_source_identity="tmdb",
            fixture_classification="synthetic",
        ),
    ]


def run_regional_ranking_audit(cases: list[RankingAuditCase] | None = None) -> list[RankingAuditResult]:
    return [run_ranking_audit_case(case) for case in (cases or build_synthetic_regional_ranking_fixtures())]


def order_results_within_groups(results: list[RankingAuditResult]) -> dict[str, list[RankingAuditResult]]:
    grouped: dict[str, list[RankingAuditResult]] = {}
    for result in results:
        grouped.setdefault(result.case.group_id, []).append(result)
    for group_id, group_results in grouped.items():
        grouped[group_id] = sorted(group_results, key=lambda item: (-item.total, item.case.case_id))
    return grouped


def capture_local_ranking_cases(session: Session, titles: list[str]) -> CapturedAuditExport:
    stmt = (
        select(Movie)
        .options(joinedload(Movie.external_ids), joinedload(Movie.observations))
        .where(Movie.canonical_title.in_(titles))
    )
    found_movies = list(session.scalars(stmt).unique())
    found_by_title = {movie.canonical_title: movie for movie in found_movies}

    cases: list[RankingAuditCase] = []
    unavailable_titles: list[str] = []
    for title in titles:
        movie = found_by_title.get(title)
        if movie is None:
            unavailable_titles.append(title)
            continue

        tmdb_id = next((external.source_movie_id for external in movie.external_ids if external.source == "tmdb"), "unknown")
        audience = _observation_by_signal(movie.observations, "audience_reception")
        popularity = _observation_by_signal(movie.observations, "popularity")
        critic = _observation_by_signal(movie.observations, "critic_consensus")
        notes = []
        if audience is not None:
            notes.append(f"audience_fetched_at={audience.fetched_at.isoformat()}")
        if popularity is not None:
            notes.append(f"popularity_fetched_at={popularity.fetched_at.isoformat()}")

        cases.append(
            RankingAuditCase(
                case_id=f"local-{title.lower().replace(' ', '-')}",
                group_id="LOCAL",
                display_label=title,
                language_or_category=movie.original_language or "unknown",
                original_language=movie.original_language,
                release_year=movie.release_year,
                normalized_query=movie.normalized_title,
                canonical_title=movie.normalized_title,
                requested_year=movie.release_year,
                vote_average=float(audience.numeric_value) if audience and audience.numeric_value is not None else None,
                rating_scale=audience.scale if audience else None,
                vote_count=audience.evidence_count if audience else None,
                popularity=float(popularity.numeric_value) if popularity and popularity.numeric_value is not None else None,
                critic_consensus_state="present" if critic is not None else "missing",
                expected_source_identity=f"tmdb:{tmdb_id}",
                fixture_classification="captured_local_observation",
                provenance_notes="; ".join(notes) if notes else None,
            )
        )

    return CapturedAuditExport(cases=cases, unavailable_titles=unavailable_titles)


def _observation_by_signal(observations: list[Observation], signal_type: str) -> Observation | None:
    return next((observation for observation in observations if observation.signal_type == signal_type), None)
