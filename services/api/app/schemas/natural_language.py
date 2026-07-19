from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.discovery import MAX_PAGE_SIZE

MAX_QUERY_LENGTH = 500


class NaturalLanguageDiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=MAX_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)

    @field_validator("query")
    @classmethod
    def _normalize_query(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("query must not be empty")
        return cleaned
