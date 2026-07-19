import hashlib
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import socket
import ssl
import subprocess
from typing import Any
from urllib.error import HTTPError as UrlLibHTTPError
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import httpx

from app.core.config import Settings
from app.core.normalization import normalize_title
from app.schemas.discovery import DiscoveryRequest


def summarize_tmdb_http_error(exc: httpx.HTTPError) -> tuple[str, str]:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code in {401, 403}:
            return ("auth_failure", f"TMDB rejected credentials with HTTP {status_code}")
        if 500 <= status_code <= 599:
            return ("provider_http_failure", f"TMDB returned HTTP {status_code}")
        return ("http_failure", f"TMDB returned HTTP {status_code}")

    if isinstance(exc, httpx.ReadTimeout):
        return ("timeout_failure", "TMDB request timed out")

    cause = exc.__cause__
    message = str(exc).lower()
    if isinstance(cause, socket.gaierror) or "nodename nor servname provided" in message or "name or service not known" in message:
        return ("dns_connectivity_failure", "DNS resolution to TMDB failed")
    if isinstance(cause, ssl.SSLError) or "ssl" in message or "tls" in message or "eof occurred in violation of protocol" in message:
        return ("tls_network_failure", "TLS handshake to TMDB failed")
    if isinstance(exc, httpx.ConnectError):
        return ("network_connect_failure", "Network connection to TMDB failed")
    if isinstance(exc, httpx.RemoteProtocolError):
        return ("protocol_failure", "TMDB connection closed unexpectedly during protocol exchange")
    return ("request_failure", exc.__class__.__name__)


@dataclass(slots=True)
class TmdbCandidate:
    source_movie_id: str
    title: str
    normalized_title: str
    release_year: int | None
    original_language: str | None
    popularity: float | None
    vote_average: float | None = None
    vote_count: int | None = None
    rating_scale: str | None = None
    media_type: str = "movie"
    overview: str | None = None
    poster_path: str | None = None
    source_url: str | None = None
    fetched_at: datetime | None = None
    fetch_status: str = "SUCCESS"
    parser_version: str = "tmdb-v1"
    raw_response_hash: str | None = None
    provider_position: int = 0


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


class UnsupportedTmdbDiscoverFilterError(ValueError):
    pass


TMDB_DISCOVER_GENRE_IDS = {
    "action": "28",
    "adventure": "12",
    "animation": "16",
    "comedy": "35",
    "crime": "80",
    "documentary": "99",
    "drama": "18",
    "family": "10751",
    "fantasy": "14",
    "history": "36",
    "horror": "27",
    "music": "10402",
    "mystery": "9648",
    "romance": "10749",
    "science-fiction": "878",
    "thriller": "53",
    "tv-movie": "10770",
    "war": "10752",
    "western": "37",
}


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
                    return self._get_json_via_curl_or_urllib(path, params=params, original_error=exc)
                await asyncio.sleep(0.2 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def _get_json_via_curl_or_urllib(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        original_error: httpx.HTTPError,
    ) -> dict[str, Any]:
        try:
            return self._get_json_via_curl(path, params=params)
        except httpx.HTTPStatusError:
            raise
        except httpx.HTTPError:
            return self._get_json_via_urllib(path, params=params, original_error=original_error)

    def _get_json_via_curl(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"

        headers = self._headers()
        command = [
            "curl",
            "--silent",
            "--show-error",
            "--location",
            "--output",
            "-",
            "--write-out",
            "\n%{http_code}",
            "--max-time",
            str(int(self._settings.api_timeout_seconds)),
            "--header",
            f"Authorization: {headers['Authorization']}",
            "--header",
            f"accept: {headers['accept']}",
            "--header",
            f"user-agent: {headers['user-agent']}",
            url,
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:
            raise httpx.ConnectError("curl fallback unavailable", request=httpx.Request("GET", url, headers=headers, params=params)) from exc

        if result.returncode != 0:
            raise httpx.ConnectError(
                result.stderr.strip() or "curl transport failed",
                request=httpx.Request("GET", url, headers=headers, params=params),
            )

        body, _, status_text = result.stdout.rpartition("\n")
        status_code = int(status_text.strip() or "0")
        self._last_response_content = body.encode("utf-8")
        if status_code >= 400:
            request = httpx.Request("GET", url, headers=headers, params=params)
            response = httpx.Response(status_code, request=request, content=self._last_response_content)
            raise httpx.HTTPStatusError(
                f"TMDB returned HTTP {status_code}",
                request=request,
                response=response,
            )
        return json.loads(body)

    def _get_json_via_urllib(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        original_error: httpx.HTTPError,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"

        request = Request(url, headers=self._headers(), method="GET")
        try:
            with urlopen(request, timeout=self._settings.api_timeout_seconds) as response:
                body = response.read()
        except UrlLibHTTPError as exc:
            request = httpx.Request("GET", url, headers=self._headers(), params=params)
            response = httpx.Response(exc.code, request=request, content=exc.read())
            raise httpx.HTTPStatusError(
                f"TMDB returned HTTP {exc.code}",
                request=request,
                response=response,
            ) from exc
        except URLError as exc:
            raise httpx.ConnectError(str(exc.reason), request=httpx.Request("GET", url, headers=self._headers(), params=params)) from exc
        except ssl.SSLError as exc:
            raise original_error from exc

        self._last_response_content = body
        return json.loads(body.decode("utf-8"))

    def _normalize_vote_average(self, value: Any) -> float | None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return float(value)

    def _normalize_vote_count(self, value: Any) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value

    def _normalize_popularity(self, value: Any) -> float | None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return float(value)

    def _normalize_optional_text(self, value: Any) -> str | None:
        if isinstance(value, str):
            return value
        return None

    def _release_year_from_date(self, value: Any) -> int | None:
        if not isinstance(value, str):
            return None
        return int(value[:4]) if len(value) >= 4 and value[:4].isdigit() else None

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
                    original_language=self._normalize_optional_text(result.get("original_language")),
                    popularity=self._normalize_popularity(result.get("popularity")),
                    vote_average=self._normalize_vote_average(result.get("vote_average")),
                    vote_count=self._normalize_vote_count(result.get("vote_count")),
                    rating_scale="0-10" if self._normalize_vote_average(result.get("vote_average")) is not None else None,
                )
            )
        return candidates

    async def discover_movies(self, request: DiscoveryRequest) -> list[TmdbCandidate]:
        if request.availability_required:
            raise UnsupportedTmdbDiscoverFilterError("availability_required is not supported by TMDB discovery yet")

        params: dict[str, str] = {
            "include_adult": "false",
            "sort_by": "popularity.desc",
            "page": str(request.page),
        }
        if request.genres:
            params["with_genres"] = ",".join(TMDB_DISCOVER_GENRE_IDS[genre] for genre in request.genres)
        if request.original_language:
            params["with_original_language"] = request.original_language
        if request.region:
            params["region"] = request.region
        if request.release_year_min is not None:
            params["primary_release_date.gte"] = f"{request.release_year_min}-01-01"
        if request.release_year_max is not None:
            params["primary_release_date.lte"] = f"{request.release_year_max}-12-31"
        if request.runtime_minutes_min is not None:
            params["with_runtime.gte"] = str(request.runtime_minutes_min)
        if request.runtime_minutes_max is not None:
            params["with_runtime.lte"] = str(request.runtime_minutes_max)
        if request.minimum_evidence_count > 0:
            params["vote_count.gte"] = str(request.minimum_evidence_count)

        payload = await self._get_json("/discover/movie", params=params)
        fetched_at = datetime.now(UTC)
        raw_hash = hashlib.sha256(self._last_response_content).hexdigest()
        capped_limit = min(request.page_size, 20)
        seen_ids: set[str] = set()
        candidates: list[TmdbCandidate] = []
        for result in payload.get("results", []):
            candidate_id = str(result.get("id") or "")
            if not candidate_id or candidate_id in seen_ids:
                continue
            title = self._normalize_optional_text(result.get("title")) or self._normalize_optional_text(
                result.get("original_title")
            )
            if not title:
                continue
            vote_average = self._normalize_vote_average(result.get("vote_average"))
            seen_ids.add(candidate_id)
            candidates.append(
                TmdbCandidate(
                    source_movie_id=candidate_id,
                    title=title,
                    normalized_title=normalize_title(title),
                    release_year=self._release_year_from_date(result.get("release_date")),
                    original_language=self._normalize_optional_text(result.get("original_language")),
                    popularity=self._normalize_popularity(result.get("popularity")),
                    vote_average=vote_average,
                    vote_count=self._normalize_vote_count(result.get("vote_count")),
                    rating_scale="0-10" if vote_average is not None else None,
                    overview=self._normalize_optional_text(result.get("overview")),
                    poster_path=self._normalize_optional_text(result.get("poster_path")),
                    source_url=f"https://www.themoviedb.org/movie/{candidate_id}",
                    fetched_at=fetched_at,
                    fetch_status="SUCCESS",
                    parser_version="tmdb-v1",
                    raw_response_hash=raw_hash,
                    provider_position=len(candidates),
                )
            )
            if len(candidates) >= capped_limit:
                break
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
        try:
            payload = await asyncio.to_thread(
                self._get_json_via_curl,
                f"/movie/{source_movie_id}/recommendations",
                params=params,
            )
        except httpx.HTTPStatusError:
            raise
        except httpx.HTTPError:
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
            vote_average = self._normalize_vote_average(result.get("vote_average"))
            vote_count = self._normalize_vote_count(result.get("vote_count"))
            seen_ids.add(candidate_id)
            candidates.append(
                TmdbCandidate(
                    source_movie_id=candidate_id,
                    title=title,
                    normalized_title=normalize_title(title),
                    release_year=release_year,
                    media_type="movie",
                    original_language=self._normalize_optional_text(result.get("original_language")),
                    popularity=self._normalize_popularity(result.get("popularity")),
                    vote_average=vote_average,
                    vote_count=vote_count,
                    rating_scale="0-10" if vote_average is not None else None,
                    overview=self._normalize_optional_text(result.get("overview")),
                    poster_path=self._normalize_optional_text(result.get("poster_path")),
                    source_url=f"https://www.themoviedb.org/movie/{candidate_id}",
                    fetched_at=fetched_at,
                    fetch_status="SUCCESS",
                    parser_version="tmdb-v1",
                    raw_response_hash=raw_hash,
                    provider_position=len(candidates),
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
