from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.discovery import DiscoveryPageMetadata, DiscoveryRequest, DiscoveryResultResponse, MAX_PAGE_SIZE

MAX_QUERY_LENGTH = 500


class NaturalLanguageDiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    region: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=MAX_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    include_shadow: bool = Field(default=False)

    @field_validator("query")
    @classmethod
    def _normalize_query(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("query must not be empty")
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


class NaturalLanguageDiscoveryResponse(BaseModel):
    status: Literal["ok"]
    query: str
    interpreted_request: DiscoveryRequest
    results: list[DiscoveryResultResponse]
    page: DiscoveryPageMetadata
