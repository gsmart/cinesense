import hashlib
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.config import Settings
from app.core.normalization import normalize_title


@dataclass(slots=True)
class TmdbCandidate:
    source_movie_id: str
    title: str
    normalized_title: str
    release_year: int | None
    original_language: str | None
    popularity: float | None
    media_type: str = "movie"
    overview: str | None = None
    poster_path: str | None = None
    source_url: str | None = None
    fetched_at: datetime | None = None
    fetch_status: str = "SUCCESS"
    parser_version: str = "tmdb-v1"
    raw_response_hash: str | None = None


@dataclass(slots=True)
class TmdbMovieBundle:
    source_movie_id: str
    source_url: str
    canonical_title: str
    normalized_title: str
    release_year: int | None
    original_language: str | None
    overview: str | None
    runtime_minutes: int | None
    poster_url: str | None
    aliases: list[str]
    observations: list[dict[str, Any]]


class TmdbAdapter:
    base_url = "https://api.themoviedb.org/3"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self._settings.tmdb_api_read_access_token)

    def _headers(self) -> dict[str, str]:
        token = self._settings.tmdb_api_read_access_token
        if not token:
            raise RuntimeError("TMDB token is not configured")
        return {
            "Authorization": f"Bearer {token}",
            "accept": "application/json",
            "user-agent": "cineSense/0.1",
        }

    async def _get_json(self, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        attempts = 3
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                async with httpx.AsyncClient(timeout=self._settings.api_timeout_seconds, trust_env=False) as client:
                    response = await client.get(f"{self.base_url}{path}", params=params, headers=self._headers())
                    response.raise_for_status()
                    self._last_response_content = response.content
                    return response.json()
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                last_error = exc
                if attempt == attempts - 1:
                    raise
                await asyncio.sleep(0.2 * (attempt + 1))
        assert last_error is not None
        raise last_error

    async def search_titles(self, query: str, year: int | None, media_type: str) -> list[TmdbCandidate]:
        if media_type != "movie":
            return []
        params = {"query": query, "include_adult": "false"}
        if year:
            params["year"] = str(year)
        payload = await self._get_json("/search/movie", params=params)
        candidates: list[TmdbCandidate] = []
        for result in payload.get("results", [])[:10]:
            title = result.get("title") or result.get("original_title")
            if not title:
                continue
            release_date = result.get("release_date") or ""
            release_year = int(release_date[:4]) if len(release_date) >= 4 and release_date[:4].isdigit() else None
            candidates.append(
                TmdbCandidate(
                    source_movie_id=str(result["id"]),
                    title=title,
                    normalized_title=normalize_title(title),
                    release_year=release_year,
                    original_language=result.get("original_language"),
                    popularity=result.get("popularity"),
                )
            )
        return candidates

    async def get_seed_recommendations(
        self,
        source_movie_id: str,
        limit: int,
        region: str | None = None,
    ) -> list[TmdbCandidate]:
        capped_limit = min(max(limit, 0), 20)
        if capped_limit == 0:
            return []

        params: dict[str, str] = {"page": "1"}
        if region:
            params["region"] = region
        payload = await self._get_json(f"/movie/{source_movie_id}/recommendations", params=params)

        fetched_at = datetime.now(UTC)
        raw_hash = hashlib.sha256(self._last_response_content).hexdigest()
        seen_ids: set[str] = set()
        candidates: list[TmdbCandidate] = []
        for result in payload.get("results", []):
            candidate_id = str(result.get("id") or "")
            if not candidate_id or candidate_id == source_movie_id or candidate_id in seen_ids:
                continue
            title = result.get("title") or result.get("original_title")
            if not title:
                continue
            release_date = result.get("release_date") or ""
            release_year = int(release_date[:4]) if len(release_date) >= 4 and release_date[:4].isdigit() else None
            seen_ids.add(candidate_id)
            candidates.append(
                TmdbCandidate(
                    source_movie_id=candidate_id,
                    title=title,
                    normalized_title=normalize_title(title),
                    release_year=release_year,
                    media_type="movie",
                    original_language=result.get("original_language"),
                    popularity=result.get("popularity"),
                    overview=result.get("overview"),
                    poster_path=result.get("poster_path"),
                    source_url=f"https://www.themoviedb.org/movie/{candidate_id}",
                    fetched_at=fetched_at,
                    fetch_status="SUCCESS",
                    parser_version="tmdb-v1",
                    raw_response_hash=raw_hash,
                )
            )
            if len(candidates) >= capped_limit:
                break
        return candidates

    async def get_movie_bundle(self, source_movie_id: str, region: str | None) -> TmdbMovieBundle:
        payload = await self._get_json(f"/movie/{source_movie_id}")

        fetched_at = datetime.now(UTC)
        raw_hash = hashlib.sha256(self._last_response_content).hexdigest()
        release_date = payload.get("release_date") or ""
        release_year = int(release_date[:4]) if len(release_date) >= 4 and release_date[:4].isdigit() else None
        title = payload.get("title") or payload.get("original_title")
        aliases = [title] if title else []
        original_title = payload.get("original_title")
        if original_title and original_title not in aliases:
            aliases.append(original_title)
        poster_path = payload.get("poster_path")
        poster_url = f"{self._settings.base_image_url}{poster_path}" if poster_path else None
        source_url = f"https://www.themoviedb.org/movie/{source_movie_id}"

        observations = [
            self._observation(
                signal_type="title_metadata",
                value={
                    "title": title,
                    "original_title": payload.get("original_title"),
                    "release_date": payload.get("release_date"),
                    "region": region,
                },
                fetched_at=fetched_at,
                raw_hash=raw_hash,
                source_movie_id=source_movie_id,
                source_url=source_url,
                fresh_delta=timedelta(days=self._settings.metadata_fresh_days),
                stale_delta=timedelta(days=self._settings.metadata_stale_days),
            ),
            self._observation(
                signal_type="audience_reception",
                value={"vote_average": payload.get("vote_average"), "vote_count": payload.get("vote_count")},
                fetched_at=fetched_at,
                raw_hash=raw_hash,
                source_movie_id=source_movie_id,
                source_url=source_url,
                fresh_delta=timedelta(days=self._settings.rating_fresh_days),
                stale_delta=timedelta(days=self._settings.rating_stale_days),
                numeric_value=payload.get("vote_average"),
                evidence_count=payload.get("vote_count"),
                scale="0-10",
            ),
            self._observation(
                signal_type="popularity",
                value={"popularity": payload.get("popularity")},
                fetched_at=fetched_at,
                raw_hash=raw_hash,
                source_movie_id=source_movie_id,
                source_url=source_url,
                fresh_delta=timedelta(hours=self._settings.popularity_fresh_hours),
                stale_delta=timedelta(days=self._settings.popularity_stale_days),
                numeric_value=payload.get("popularity"),
            ),
        ]

        return TmdbMovieBundle(
            source_movie_id=source_movie_id,
            source_url=source_url,
            canonical_title=title or "Unknown title",
            normalized_title=normalize_title(title or "unknown title"),
            release_year=release_year,
            original_language=payload.get("original_language"),
            overview=payload.get("overview"),
            runtime_minutes=payload.get("runtime"),
            poster_url=poster_url,
            aliases=aliases,
            observations=observations,
        )

    def _observation(
        self,
        *,
        signal_type: str,
        value: dict[str, Any],
        fetched_at: datetime,
        raw_hash: str,
        source_movie_id: str,
        source_url: str,
        fresh_delta: timedelta,
        stale_delta: timedelta,
        numeric_value: float | None = None,
        evidence_count: int | None = None,
        scale: str | None = None,
    ) -> dict[str, Any]:
        return {
            "signal_type": signal_type,
            "value": value,
            "numeric_value": numeric_value,
            "evidence_count": evidence_count,
            "scale": scale,
            "fetched_at": fetched_at,
            "fresh_until": fetched_at + fresh_delta,
            "stale_until": fetched_at + stale_delta,
            "last_success_at": fetched_at,
            "source_url": source_url,
            "fetch_status": "SUCCESS",
            "parser_version": "tmdb-v1",
            "raw_response_hash": raw_hash,
            "source_movie_id": source_movie_id,
        }
