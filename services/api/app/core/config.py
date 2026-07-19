from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+psycopg://cinesense:cinesense@localhost:5432/cinesense",
        alias="DATABASE_URL",
    )
    tmdb_api_read_access_token: str | None = Field(
        default=None,
        alias="TMDB_API_READ_ACCESS_TOKEN",
    )
    cinesense_llm_enabled: bool = Field(default=False, alias="CINESENSE_LLM_ENABLED")
    cinesense_llm_base_url: str | None = Field(default=None, alias="CINESENSE_LLM_BASE_URL")
    cinesense_llm_api_key: str | None = Field(default=None, alias="CINESENSE_LLM_API_KEY")
    cinesense_llm_model: str | None = Field(default=None, alias="CINESENSE_LLM_MODEL")
    cinesense_llm_timeout_seconds: float = Field(default=10.0, alias="CINESENSE_LLM_TIMEOUT_SECONDS", gt=0, le=30)
    active_ranking_version: str = Field(default="cine-score-v1", alias="CINESENSE_ACTIVE_RANKING_VERSION")
    shadow_ranking_version: str = Field(default="disabled", alias="CINESENSE_SHADOW_RANKING_VERSION")
    fallback_ranking_version: str = Field(default="cine-score-v1", alias="CINESENSE_FALLBACK_RANKING_VERSION")
    api_timeout_seconds: float = 10.0
    wikidata_sparql_endpoint: str = Field(
        default="https://query.wikidata.org/sparql",
        alias="WIKIDATA_SPARQL_ENDPOINT",
    )
    wikidata_user_agent: str = Field(
        default="cineSenseRegionalEvidence/0.1 (https://github.com/gsmart/cinesense)",
        alias="WIKIDATA_USER_AGENT",
    )
    wikidata_batch_size: int = Field(default=20, alias="WIKIDATA_BATCH_SIZE", gt=0, le=50)
    wikidata_timeout_seconds: float = Field(default=10.0, alias="WIKIDATA_TIMEOUT_SECONDS", gt=0, le=30)
    metadata_fresh_days: int = 30
    metadata_stale_days: int = 90
    popularity_fresh_hours: int = 24
    popularity_stale_days: int = 7
    rating_fresh_days: int = 7
    rating_stale_days: int = 30
    base_image_url: str = "https://image.tmdb.org/t/p/w500"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
