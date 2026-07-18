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
    api_timeout_seconds: float = 10.0
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

