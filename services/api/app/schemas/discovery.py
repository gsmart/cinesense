from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CURRENT_YEAR_PLUS_ONE = datetime.now().year + 1
MIN_RELEASE_YEAR = 1888
MIN_RUNTIME_MINUTES = 1
MAX_RUNTIME_MINUTES = 400
MAX_PAGE_SIZE = 20

SUPPORTED_GENRE_SLUGS = {
    "action",
    "adventure",
    "animation",
    "comedy",
    "crime",
    "documentary",
    "drama",
    "family",
    "fantasy",
    "history",
    "horror",
    "music",
    "mystery",
    "romance",
    "science-fiction",
    "thriller",
    "tv-movie",
    "war",
    "western",
}


class DiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_type: Literal["movie"] = "movie"
    genres: list[str] = Field(default_factory=list)
    original_language: str | None = None
    region: str | None = None
    release_year_min: int | None = Field(default=None, ge=MIN_RELEASE_YEAR, le=CURRENT_YEAR_PLUS_ONE)
    release_year_max: int | None = Field(default=None, ge=MIN_RELEASE_YEAR, le=CURRENT_YEAR_PLUS_ONE)
    runtime_minutes_min: int | None = Field(default=None, ge=MIN_RUNTIME_MINUTES, le=MAX_RUNTIME_MINUTES)
    runtime_minutes_max: int | None = Field(default=None, ge=MIN_RUNTIME_MINUTES, le=MAX_RUNTIME_MINUTES)
    minimum_evidence_count: int = Field(default=0, ge=0)
    availability_required: bool = False
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=MAX_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)

    @field_validator("genres", mode="before")
    @classmethod
    def _normalize_genres_input(cls, value: object) -> object:
        if value is None:
            return []
        return value

    @field_validator("genres")
    @classmethod
    def _normalize_genres(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = value.strip().lower()
            if not cleaned:
                raise ValueError("genres must not contain empty values")
            if cleaned not in SUPPORTED_GENRE_SLUGS:
                raise ValueError(f"unsupported genre slug: {cleaned}")
            if cleaned not in seen:
                seen.add(cleaned)
                normalized.append(cleaned)
        return sorted(normalized)

    @field_validator("original_language")
    @classmethod
    def _normalize_original_language(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lower()
        if not cleaned:
            return None
        if not cleaned.isascii() or not cleaned.isalpha() or len(cleaned) != 2:
            raise ValueError("original_language must be a 2-letter ISO-shaped code")
        return cleaned

    @field_validator("region")
    @classmethod
    def _normalize_region(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().upper()
        if not cleaned:
            return None
        if not cleaned.isascii() or not cleaned.isalpha() or len(cleaned) != 2:
            raise ValueError("region must be a 2-letter ISO-shaped code")
        return cleaned

    @model_validator(mode="after")
    def _validate_ranges_and_narrowing(self) -> "DiscoveryRequest":
        if self.release_year_min is not None and self.release_year_max is not None:
            if self.release_year_min > self.release_year_max:
                raise ValueError("release_year_min must be less than or equal to release_year_max")

        if self.runtime_minutes_min is not None and self.runtime_minutes_max is not None:
            if self.runtime_minutes_min > self.runtime_minutes_max:
                raise ValueError("runtime_minutes_min must be less than or equal to runtime_minutes_max")

        if self.availability_required and not self.region:
            raise ValueError("availability_required=true requires region")

        has_meaningful_narrowing = any(
            (
                bool(self.genres),
                self.original_language is not None,
                self.release_year_min is not None or self.release_year_max is not None,
                self.runtime_minutes_min is not None or self.runtime_minutes_max is not None,
                self.minimum_evidence_count > 0,
                self.availability_required and self.region is not None,
            )
        )
        if not has_meaningful_narrowing:
            raise ValueError("unrestricted discovery requests are not allowed")

        return self


class DiscoveryMovieResponse(BaseModel):
    movie_id: str
    canonical_title: str
    release_year: int | None
    media_type: str
    original_language: str | None = None
    overview: str | None = None
    poster_url: str | None = None


class DiscoveryProvenanceResponse(BaseModel):
    source: str
    source_movie_id: str
    source_url: str | None


class DiscoveryResultResponse(BaseModel):
    movie: DiscoveryMovieResponse
    tmdb_source_movie_id: str
    provider_position: int
    score: float
    score_version: str
    score_components: dict[str, float | None]
    missing_signals: list[str]
    provenance: DiscoveryProvenanceResponse
    freshness: dict[str, str]


class DiscoveryPageMetadata(BaseModel):
    page: int
    requested_page_size: int
    returned_count: int
    max_page_size: Literal[20] = 20


class DiscoveryResponse(BaseModel):
    status: Literal["ok"]
    request: DiscoveryRequest
    results: list[DiscoveryResultResponse]
    page: DiscoveryPageMetadata
