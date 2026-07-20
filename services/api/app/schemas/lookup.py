from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LookupRequest(BaseModel):
    title: str = Field(min_length=1)
    year: int | None = Field(default=None, ge=1888, le=2100)
    region: str | None = Field(default=None, min_length=2, max_length=2)
    media_type: Literal["movie"] = "movie"
    include_shadow: bool = Field(default=False)


class DisambiguationChoice(BaseModel):
    movie_id: str
    title: str
    release_year: int | None
    source: str
    source_movie_id: str


class ObservationResponse(BaseModel):
    signal_type: str
    source: str
    fetched_at: datetime
    fresh_until: datetime | None
    stale_until: datetime | None
    freshness_state: str
    value: dict
    scale: str | None
    evidence_count: int | None
    source_url: str | None
    fetch_status: str


class ScoreResponse(BaseModel):
    version: str
    total: float
    components: dict[str, float | None]
    missing_signals: list[str]


class ShadowComparisonResponse(BaseModel):
    authoritative: bool = False
    shadow_only: bool = True
    v1_score: float | None = None
    v2_score: float | None = None
    v1_rank: int | None = None
    v2_rank: int | None = None
    rank_movement: int | None = None
    score_delta: float | None = None
    score_version: str = "cine-score-v2-shadow-1"
    evidence_gate: str | None = None
    review_status: str | None = "PENDING"
    activation_eligible: bool = False
    ineligible_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)


class MovieResponse(BaseModel):
    movie_id: str
    canonical_title: str
    release_year: int | None
    media_type: str
    original_language: str | None
    overview: str | None
    runtime_minutes: int | None
    poster_url: str | None
    aliases: list[str]
    source: str
    source_movie_id: str
    source_url: str | None
    freshness: dict[str, str]
    observations: list[ObservationResponse]
    missing_signals: list[str]
    score: ScoreResponse
    shadow_comparison: ShadowComparisonResponse | None = None


class LookupResponse(BaseModel):
    status: Literal["resolved", "disambiguation"]
    normalized_title: str
    region: str | None
    media_type: Literal["movie"]
    source: Literal["local_cache", "tmdb"]
    movie: MovieResponse | None = None
    disambiguation_choices: list[DisambiguationChoice] = Field(default_factory=list)
