from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, AliasChoices

from app.schemas.lookup import ShadowComparisonResponse


class RecommendationsRequest(BaseModel):
    seed_movie_id: UUID
    region: str | None = Field(default=None, min_length=2, max_length=2)
    page_size: int = Field(default=20, ge=1, le=20)
    include_shadow: bool = Field(default=False)


class SeedMovieResponse(BaseModel):
    movie_id: str
    canonical_title: str
    release_year: int | None
    media_type: str


class RecommendationMovieResponse(BaseModel):
    movie_id: str
    canonical_title: str
    release_year: int | None
    media_type: str
    original_language: str | None = None
    overview: str | None = None
    poster_url: str | None = None


class RecommendationProvenanceResponse(BaseModel):
    source: str
    source_movie_id: str
    source_url: str | None


class RecommendationResponse(BaseModel):
    movie: RecommendationMovieResponse
    tmdb_source_movie_id: str
    provider_position: int
    score: float
    score_version: str
    score_components: dict[str, float | None]
    missing_signals: list[str]
    provenance: RecommendationProvenanceResponse
    freshness: dict[str, str]
    shadow_comparison: ShadowComparisonResponse | None = None


class RecommendationPageMetadata(BaseModel):
    page: Literal[1] = 1
    requested_page_size: int
    returned_count: int
    max_page_size: Literal[20] = 20


class RecommendationsResponse(BaseModel):
    status: Literal["ok"]
    seed: SeedMovieResponse
    region: str | None
    limit: int
    recommendations: list[RecommendationResponse] = Field(
        validation_alias=AliasChoices("recommendations", "results")
    )
    page: RecommendationPageMetadata
