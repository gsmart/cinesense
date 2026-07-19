from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Protocol
from zipfile import ZipFile

import httpx

from app.adapters.tmdb import TmdbAdapter, TmdbCandidate, summarize_tmdb_http_error
from app.core.config import Settings
from app.schemas.discovery import DiscoveryRequest

SCRIPT_VERSION = "regional-evidence-v1"
DEFAULT_LANGUAGES = ("mr", "ml", "ta")
DEFAULT_LIMIT_PER_LANGUAGE = 50
DEFAULT_OUTPUT_ROOT = Path("/tmp/cinesense-regional-evidence")
WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
WIKIDATA_USER_AGENT = "cineSenseRegionalEvidence/0.1 (https://github.com/gsmart/cinesense)"
WIKIDATA_ACCEPT = "application/sparql-results+json"
WIKIDATA_MAX_RETRIES = 1

WIKIDATA_EXACT = "EXACT_IDENTIFIER_MATCH"
WIKIDATA_NONE = "NO_MATCH"
WIKIDATA_AMBIGUOUS = "AMBIGUOUS_REVIEW_REQUIRED"
WIKIDATA_ERROR = "SOURCE_ERROR"

RECOGNITION_EXACT = "EXACT_METADATA_MATCH"
RECOGNITION_NONE = "NO_MATCH"
RECOGNITION_AMBIGUOUS = "AMBIGUOUS_REVIEW_REQUIRED"
UNICODE_SPACE_RE = re.compile(r"\s+")


class WikidataClient(Protocol):
    async def fetch_by_tmdb_ids(self, tmdb_ids: list[str]) -> tuple[dict[str, list[dict[str, Any]]], str, str]: ...


@dataclass(frozen=True)
class AwardsRecord:
    source_name: str
    source_record_id: str
    source_url: str | None
    loaded_at: str
    raw_source_hash: str
    parser_version: str
    warnings: list[str]
    award_category: str | None
    award_name: str | None
    film_title: str | None
    normalized_title: str | None
    award_year: int | None
    language: str | None


class WikidataFetchError(RuntimeError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


class DefaultWikidataClient:
    def __init__(self, *, settings: Settings) -> None:
        self.settings = settings

    async def fetch_by_tmdb_ids(self, tmdb_ids: list[str]) -> tuple[dict[str, list[dict[str, Any]]], str, str]:
        query = self._query_for_tmdb_ids(tmdb_ids)
        last_error: WikidataFetchError | None = None
        for attempt in range(WIKIDATA_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=self.settings.wikidata_timeout_seconds, trust_env=False) as client:
                    response = await client.get(
                        self.settings.wikidata_sparql_endpoint,
                        params={"query": query, "format": "json"},
                        headers={"accept": WIKIDATA_ACCEPT, "user-agent": self.settings.wikidata_user_agent},
                    )
                if response.status_code == 429 and attempt < WIKIDATA_MAX_RETRIES:
                    await asyncio.sleep(_retry_delay_seconds(response.headers.get("Retry-After")))
                    continue
                if 500 <= response.status_code < 600 and attempt < WIKIDATA_MAX_RETRIES:
                    await asyncio.sleep(1.0)
                    continue
                if response.status_code >= 400:
                    raise WikidataFetchError(f"http_{response.status_code}")
                content_type = response.headers.get("content-type", "")
                if WIKIDATA_ACCEPT not in content_type and "application/json" not in content_type:
                    raise WikidataFetchError("unexpected_content_type")
                body = response.content
                try:
                    payload = response.json()
                except json.JSONDecodeError as exc:
                    raise WikidataFetchError("malformed_json") from exc
                bindings = payload.get("results", {}).get("bindings")
                if not isinstance(bindings, list):
                    raise WikidataFetchError("unexpected_response_shape")
                break
            except WikidataFetchError as exc:
                last_error = exc
                if exc.category.startswith("http_5") and attempt < WIKIDATA_MAX_RETRIES:
                    await asyncio.sleep(1.0)
                    continue
                raise
            except httpx.TimeoutException as exc:
                raise WikidataFetchError("timeout") from exc
            except httpx.HTTPError as exc:
                raise WikidataFetchError("transport_error") from exc
        else:
            raise last_error or WikidataFetchError("unexpected_error")

        grouped: dict[str, list[dict[str, Any]]] = {}
        for binding in payload.get("results", {}).get("bindings", []):
            tmdb_id = _binding_text(binding, "tmdbId")
            if not tmdb_id:
                continue
            grouped.setdefault(tmdb_id, []).append(binding)
        return grouped, hashlib.sha256(body).hexdigest(), datetime.now(UTC).isoformat()

    def _query_for_tmdb_ids(self, tmdb_ids: list[str]) -> str:
        values = " ".join(f'"{tmdb_id}"' for tmdb_id in tmdb_ids)
        return f"""
SELECT ?tmdbId ?item ?itemLabel ?label ?labelLang ?altLabel ?altLang ?imdbId ?languageLabel ?countryLabel ?directorLabel ?publicationDate
WHERE {{
  VALUES ?tmdbId {{ {values} }}
  ?item wdt:P4947 ?tmdbId .
  OPTIONAL {{
    ?item rdfs:label ?label .
    BIND(LANG(?label) AS ?labelLang)
    FILTER(?labelLang IN ("en", "mr", "ml", "ta"))
  }}
  OPTIONAL {{
    ?item skos:altLabel ?altLabel .
    BIND(LANG(?altLabel) AS ?altLang)
    FILTER(?altLang IN ("en", "mr", "ml", "ta"))
  }}
  OPTIONAL {{ ?item wdt:P345 ?imdbId . }}
  OPTIONAL {{ ?item wdt:P364 ?language . }}
  OPTIONAL {{ ?item wdt:P495 ?country . }}
  OPTIONAL {{ ?item wdt:P57 ?director . }}
  OPTIONAL {{ ?item wdt:P577 ?publicationDate . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mr,ml,ta,[AUTO_LANGUAGE]" . }}
}}
"""


class RegionalEvidencePipeline:
    def __init__(
        self,
        *,
        settings: Settings,
        tmdb: TmdbAdapter,
        wikidata: WikidataClient | None = None,
    ) -> None:
        self.settings = settings
        self.tmdb = tmdb
        self.wikidata = wikidata or DefaultWikidataClient(settings=settings)

    async def build(
        self,
        *,
        languages: list[str],
        limit_per_language: int,
        output_dir: Path,
        national_awards_file: Path | None = None,
    ) -> dict[str, Any]:
        run_id = output_dir.name
        started_at = datetime.now(UTC).isoformat()
        output_dir.mkdir(parents=True, exist_ok=True)

        manifest: dict[str, Any] = {
            "run_id": run_id,
            "started_at": started_at,
            "requested_languages": languages,
            "limit_per_language": limit_per_language,
            "sources_used": ["tmdb", "wikidata", "national_film_awards" if national_awards_file else None],
            "source_urls": {
                "tmdb": "https://developer.themoviedb.org/",
                "wikidata": WIKIDATA_SPARQL_URL,
                "national_film_awards": "https://data.gov.in/catalog/national-film-awards" if national_awards_file else None,
            },
            "script_version": SCRIPT_VERSION,
            "record_counts": {},
            "error_counts": {},
            "output_hashes": {},
            "national_awards_file_supplied": national_awards_file is not None,
            "warnings": [],
        }

        movies, tmdb_errors = await self._collect_tmdb_movies(languages=languages, limit_per_language=limit_per_language)
        movies_path = output_dir / "movies.jsonl"
        _write_jsonl(movies_path, movies)

        wikidata_records = await self._build_wikidata_matches(movies)
        wikidata_path = output_dir / "wikidata_matches.jsonl"
        _write_jsonl(wikidata_path, wikidata_records)

        awards_records: list[dict[str, Any]] = []
        awards_stage_error: str | None = None
        if national_awards_file is not None:
            try:
                awards_records = [asdict(record) for record in load_national_awards_records(national_awards_file)]
            except Exception as exc:
                awards_stage_error = f"{exc.__class__.__name__}: {exc}"
        awards_path = output_dir / "national_awards_records.jsonl"
        _write_jsonl(awards_path, awards_records)

        recognition_records = build_recognition_match_candidates(awards_records=awards_records, movies=movies)
        recognition_path = output_dir / "recognition_match_candidates.jsonl"
        _write_jsonl(recognition_path, recognition_records)

        coverage_summary = build_coverage_summary(
            languages=languages,
            limit_per_language=limit_per_language,
            movies=movies,
            wikidata_records=wikidata_records,
            awards_records=awards_records,
            recognition_records=recognition_records,
            awards_available=national_awards_file is not None and awards_stage_error is None,
        )
        coverage_path = output_dir / "coverage_summary.json"
        coverage_path.write_text(json.dumps(coverage_summary, indent=2, sort_keys=True), encoding="utf-8")

        manifest["record_counts"] = {
            "movies": len(movies),
            "wikidata_matches": len(wikidata_records),
            "national_awards_records": len(awards_records),
            "recognition_match_candidates": len(recognition_records),
        }
        manifest["error_counts"] = {
            "tmdb_errors": len(tmdb_errors),
            "wikidata_source_errors": sum(1 for record in wikidata_records if record["match_status"] == WIKIDATA_ERROR),
            "recognition_stage_errors": 1 if awards_stage_error else 0,
        }
        manifest["warnings"].extend(tmdb_errors)
        if awards_stage_error:
            manifest["warnings"].append(f"national_awards_stage_failed:{awards_stage_error}")

        for path in (
            movies_path,
            wikidata_path,
            awards_path,
            recognition_path,
            coverage_path,
        ):
            manifest["output_hashes"][path.name] = _sha256_path(path)

        manifest["completed_at"] = datetime.now(UTC).isoformat()
        manifest_path = output_dir / "run_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        manifest["output_hashes"][manifest_path.name] = _sha256_path(manifest_path)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

        return manifest

    async def _collect_tmdb_movies(
        self,
        *,
        languages: list[str],
        limit_per_language: int,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        if not self.tmdb.enabled:
            raise RuntimeError("TMDB token is not configured")

        movies: list[dict[str, Any]] = []
        warnings: list[str] = []
        seen_ids: set[str] = set()
        for language in languages:
            language_movies: list[dict[str, Any]] = []
            page = 1
            while len(language_movies) < limit_per_language:
                page_size = min(20, limit_per_language - len(language_movies))
                request = DiscoveryRequest(original_language=language, page=page, page_size=page_size)
                try:
                    candidates = await self.tmdb.discover_movies(request)
                except httpx.HTTPError as exc:
                    category, detail = summarize_tmdb_http_error(exc)
                    if category == "auth_failure":
                        raise RuntimeError(detail) from exc
                    warnings.append(f"tmdb:{language}:page={page}:{category}")
                    break
                if not candidates:
                    break
                for candidate in candidates:
                    if candidate.source_movie_id in seen_ids:
                        continue
                    seen_ids.add(candidate.source_movie_id)
                    language_movies.append(
                        _movie_record_from_candidate(
                            candidate,
                            requested_language=language,
                            provider_position=len(language_movies),
                            provider_page=page,
                        )
                    )
                    if len(language_movies) >= limit_per_language:
                        break
                page += 1
            movies.extend(language_movies)
        return movies, warnings

    async def _build_wikidata_matches(self, movies: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tmdb_ids = [movie["source_record_id"] for movie in movies]
        if not tmdb_ids:
            return []

        grouped_rows: dict[str, list[dict[str, Any]]] = {}
        response_hashes: dict[str, str] = {}
        fetched_times: dict[str, str] = {}
        errors: set[str] = set()
        error_categories: dict[str, str] = {}
        for chunk in _chunked(tmdb_ids, self.settings.wikidata_batch_size):
            try:
                rows, response_hash, fetched_at = await self.wikidata.fetch_by_tmdb_ids(chunk)
            except WikidataFetchError as exc:
                for tmdb_id in chunk:
                    errors.add(tmdb_id)
                    error_categories[tmdb_id] = exc.category
                continue
            except Exception:
                for tmdb_id in chunk:
                    errors.add(tmdb_id)
                    error_categories[tmdb_id] = "unexpected_error"
                continue
            for tmdb_id, values in rows.items():
                grouped_rows[tmdb_id] = values
                response_hashes[tmdb_id] = response_hash
                fetched_times[tmdb_id] = fetched_at

        records: list[dict[str, Any]] = []
        for movie in movies:
            tmdb_id = movie["source_record_id"]
            if tmdb_id in errors:
                records.append(
                    {
                        "tmdb_source_movie_id": tmdb_id,
                        "source_name": "wikidata",
                        "source_record_id": tmdb_id,
                        "source_url": f"https://www.wikidata.org/wiki/Special:EntityData/{tmdb_id}",
                        "fetched_at": datetime.now(UTC).isoformat(),
                        "raw_response_hash": None,
                        "parser_version": SCRIPT_VERSION,
                        "match_status": WIKIDATA_ERROR,
                        "warnings": [f"wikidata_batch_failed:{error_categories.get(tmdb_id, 'unknown_error')}"],
                        "wikidata_qid": None,
                        "english_label": None,
                        "titles": [],
                        "alternate_titles": [],
                        "imdb_id": None,
                        "original_languages": [],
                        "countries_of_origin": [],
                        "directors": [],
                        "publication_date": None,
                    }
                )
                continue

            rows = grouped_rows.get(tmdb_id, [])
            if not rows:
                records.append(
                    {
                        "tmdb_source_movie_id": tmdb_id,
                        "source_name": "wikidata",
                        "source_record_id": tmdb_id,
                        "source_url": f"https://query.wikidata.org/#SELECT%20*%20WHERE%20%7B%20%3Fitem%20wdt%3AP4947%20%22{tmdb_id}%22%20%7D",
                        "fetched_at": fetched_times.get(tmdb_id, datetime.now(UTC).isoformat()),
                        "raw_response_hash": response_hashes.get(tmdb_id),
                        "parser_version": SCRIPT_VERSION,
                        "match_status": WIKIDATA_NONE,
                        "warnings": [],
                        "wikidata_qid": None,
                        "english_label": None,
                        "titles": [],
                        "alternate_titles": [],
                        "imdb_id": None,
                        "original_languages": [],
                        "countries_of_origin": [],
                        "directors": [],
                        "publication_date": None,
                    }
                )
                continue

            item_groups: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                item = _binding_text(row, "item")
                if item:
                    item_groups.setdefault(item, []).append(row)
            if len(item_groups) != 1:
                records.append(
                    {
                        "tmdb_source_movie_id": tmdb_id,
                        "source_name": "wikidata",
                        "source_record_id": tmdb_id,
                        "source_url": f"https://query.wikidata.org/#SELECT%20*%20WHERE%20%7B%20%3Fitem%20wdt%3AP4947%20%22{tmdb_id}%22%20%7D",
                        "fetched_at": fetched_times.get(tmdb_id, datetime.now(UTC).isoformat()),
                        "raw_response_hash": response_hashes.get(tmdb_id),
                        "parser_version": SCRIPT_VERSION,
                        "match_status": WIKIDATA_AMBIGUOUS,
                        "warnings": ["multiple_wikidata_items"],
                        "wikidata_qid": None,
                        "english_label": None,
                        "titles": [],
                        "alternate_titles": [],
                        "imdb_id": None,
                        "original_languages": [],
                        "countries_of_origin": [],
                        "directors": [],
                        "publication_date": None,
                    }
                )
                continue

            item_url, item_rows = next(iter(item_groups.items()))
            labels = _collect_multilingual_labels(item_rows, "label", "labelLang")
            alt_labels = _collect_multilingual_labels(item_rows, "altLabel", "altLang")
            english_label = next((label["value"] for label in labels if label["language"] == "en"), None)
            records.append(
                {
                    "tmdb_source_movie_id": tmdb_id,
                    "source_name": "wikidata",
                    "source_record_id": item_url.rsplit("/", 1)[-1],
                    "source_url": item_url,
                    "fetched_at": fetched_times.get(tmdb_id, datetime.now(UTC).isoformat()),
                    "raw_response_hash": response_hashes.get(tmdb_id),
                    "parser_version": SCRIPT_VERSION,
                    "match_status": WIKIDATA_EXACT,
                    "warnings": [],
                    "wikidata_qid": item_url.rsplit("/", 1)[-1],
                    "english_label": english_label,
                    "titles": labels,
                    "alternate_titles": alt_labels,
                    "imdb_id": _first_non_null(item_rows, "imdbId"),
                    "original_languages": _collect_unique_values(item_rows, "languageLabel"),
                    "countries_of_origin": _collect_unique_values(item_rows, "countryLabel"),
                    "directors": _collect_unique_values(item_rows, "directorLabel"),
                    "publication_date": _first_non_null(item_rows, "publicationDate"),
                }
            )
        return records


def load_national_awards_records(path: Path) -> list[AwardsRecord]:
    suffix = path.suffix.lower()
    if suffix == ".zip":
        with ZipFile(path) as bundle:
            members = sorted(name for name in bundle.namelist() if name.lower().endswith((".csv", ".json")))
            if not members:
                raise ValueError("zip file does not contain a CSV or JSON dataset")
            member = members[0]
            raw = bundle.read(member)
            source_url = f"{path.resolve()}#{member}"
            rows = _load_tabular_rows(member, raw)
    else:
        raw = path.read_bytes()
        source_url = str(path.resolve())
        rows = _load_tabular_rows(path.name, raw)

    loaded_at = datetime.now(UTC).isoformat()
    records: list[AwardsRecord] = []
    for index, row in enumerate(rows, start=1):
        title = _first_text(row, ["film_title", "film", "movie", "title", "name_of_film"])
        language = _first_text(row, ["language", "film_language"])
        award_year = _first_int(row, ["award_year", "year", "award_year_edition", "award_year_or_edition"])
        source_record_id = _first_text(row, ["id", "record_id", "row_id"]) or str(index)
        row_bytes = json.dumps(row, sort_keys=True, ensure_ascii=False).encode("utf-8")
        records.append(
            AwardsRecord(
                source_name="national_film_awards_ogd",
                source_record_id=source_record_id,
                source_url=source_url,
                loaded_at=loaded_at,
                raw_source_hash=hashlib.sha256(row_bytes).hexdigest(),
                parser_version=SCRIPT_VERSION,
                warnings=[],
                award_category=_first_text(row, ["award_category", "category"]),
                award_name=_first_text(row, ["award_name", "award", "award_title"]),
                film_title=title,
                normalized_title=normalize_evidence_title(title) if title else None,
                award_year=award_year,
                language=language.strip().lower() if isinstance(language, str) and language.strip() else None,
            )
        )
    return records


def build_recognition_match_candidates(
    *,
    awards_records: list[dict[str, Any]],
    movies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_title: dict[str, list[dict[str, Any]]] = {}
    for movie in movies:
        by_title.setdefault(movie["normalized_title"], []).append(movie)

    results: list[dict[str, Any]] = []
    for record in awards_records:
        normalized_title = record.get("normalized_title")
        candidates = by_title.get(normalized_title, []) if normalized_title else []
        status = RECOGNITION_NONE
        warnings: list[str] = []
        matched_movie_ids: list[str] = []
        if not candidates:
            status = RECOGNITION_NONE
        elif len(candidates) > 1:
            status = RECOGNITION_AMBIGUOUS
            matched_movie_ids = [movie["source_record_id"] for movie in candidates]
            warnings.append("multiple_movies_for_title")
        else:
            movie = candidates[0]
            matched_movie_ids = [movie["source_record_id"]]
            year_compatible = record.get("award_year") is not None and movie.get("release_year") == record.get("award_year")
            language_compatible = record.get("language") is not None and movie.get("original_language") == record.get("language")
            if year_compatible and language_compatible:
                status = RECOGNITION_EXACT
            else:
                status = RECOGNITION_AMBIGUOUS
                if record.get("award_year") is None or movie.get("release_year") is None:
                    warnings.append("year_missing")
                elif movie.get("release_year") != record.get("award_year"):
                    warnings.append("year_conflict")
                if record.get("language") is None or movie.get("original_language") is None:
                    warnings.append("language_missing")
                elif movie.get("original_language") != record.get("language"):
                    warnings.append("language_conflict")

        results.append(
            {
                "source_name": record.get("source_name"),
                "source_record_id": record.get("source_record_id"),
                "source_url": record.get("source_url"),
                "loaded_at": record.get("loaded_at"),
                "raw_source_hash": record.get("raw_source_hash"),
                "parser_version": record.get("parser_version"),
                "match_status": status,
                "warnings": warnings,
                "award_category": record.get("award_category"),
                "award_name": record.get("award_name"),
                "film_title": record.get("film_title"),
                "normalized_title": normalized_title,
                "award_year": record.get("award_year"),
                "language": record.get("language"),
                "matched_tmdb_movie_ids": matched_movie_ids,
            }
        )
    return results


def build_coverage_summary(
    *,
    languages: list[str],
    limit_per_language: int,
    movies: list[dict[str, Any]],
    wikidata_records: list[dict[str, Any]],
    awards_records: list[dict[str, Any]],
    recognition_records: list[dict[str, Any]],
    awards_available: bool,
) -> dict[str, Any]:
    wikidata_by_id = {record["tmdb_source_movie_id"]: record for record in wikidata_records}
    per_language: dict[str, dict[str, Any]] = {}
    for language in languages:
        language_movies = [movie for movie in movies if movie["requested_language"] == language]
        language_wikidata = [wikidata_by_id[movie["source_record_id"]] for movie in language_movies if movie["source_record_id"] in wikidata_by_id]
        language_recognition = [record for record in recognition_records if record.get("language") == language]
        per_language[language] = _coverage_metrics(
            requested_count=limit_per_language,
            movies=language_movies,
            wikidata_records=language_wikidata,
            awards_records=[record for record in awards_records if record.get("language") == language],
            recognition_records=language_recognition,
            awards_available=awards_available,
        )

    total = _coverage_metrics(
        requested_count=len(languages) * limit_per_language,
        movies=movies,
        wikidata_records=wikidata_records,
        awards_records=awards_records,
        recognition_records=recognition_records,
        awards_available=awards_available,
    )
    return {"per_language": per_language, "total": total}


def _coverage_metrics(
    *,
    requested_count: int,
    movies: list[dict[str, Any]],
    wikidata_records: list[dict[str, Any]],
    awards_records: list[dict[str, Any]],
    recognition_records: list[dict[str, Any]],
    awards_available: bool,
) -> dict[str, Any]:
    movie_count = len(movies)
    exact_wikidata = sum(1 for record in wikidata_records if record["match_status"] == WIKIDATA_EXACT)
    missing_wikidata = sum(1 for record in wikidata_records if record["match_status"] == WIKIDATA_NONE)
    ambiguous_wikidata = sum(1 for record in wikidata_records if record["match_status"] == WIKIDATA_AMBIGUOUS)
    source_error_wikidata = sum(1 for record in wikidata_records if record["match_status"] == WIKIDATA_ERROR)
    return {
        "requested_movie_count": requested_count,
        "collected_tmdb_movie_count": movie_count,
        "movies_with_rating": sum(1 for movie in movies if movie.get("vote_average") is not None),
        "movies_with_vote_count": sum(1 for movie in movies if movie.get("vote_count") is not None),
        "movies_with_popularity": sum(1 for movie in movies if movie.get("popularity") is not None),
        "exact_wikidata_matches": exact_wikidata,
        "missing_wikidata_matches": missing_wikidata,
        "ambiguous_wikidata_matches": ambiguous_wikidata,
        "wikidata_source_errors": source_error_wikidata,
        "movies_with_native_or_alternate_titles": sum(
            1
            for record in wikidata_records
            if record.get("titles") or record.get("alternate_titles")
        ),
        "movies_with_imdb_ids_from_wikidata": sum(1 for record in wikidata_records if record.get("imdb_id")),
        "national_film_awards_records_loaded": len(awards_records) if awards_available else None,
        "exact_recognition_matches": sum(1 for record in recognition_records if record["match_status"] == RECOGNITION_EXACT)
        if awards_available
        else None,
        "ambiguous_recognition_matches": sum(
            1 for record in recognition_records if record["match_status"] == RECOGNITION_AMBIGUOUS
        )
        if awards_available
        else None,
        "unmatched_recognition_records": sum(1 for record in recognition_records if record["match_status"] == RECOGNITION_NONE)
        if awards_available
        else None,
        "percentages": {
            "collected_tmdb_movie_count_pct": _pct(movie_count, requested_count),
            "movies_with_rating_pct": _pct(sum(1 for movie in movies if movie.get("vote_average") is not None), movie_count),
            "exact_wikidata_matches_pct": _pct(exact_wikidata, movie_count),
            "movies_with_imdb_ids_from_wikidata_pct": _pct(
                sum(1 for record in wikidata_records if record.get("imdb_id")), movie_count
            ),
        },
    }


def _movie_record_from_candidate(
    candidate: TmdbCandidate,
    *,
    requested_language: str,
    provider_position: int,
    provider_page: int,
) -> dict[str, Any]:
    return {
        "source_name": "tmdb",
        "source_record_id": candidate.source_movie_id,
        "source_url": candidate.source_url,
        "fetched_at": candidate.fetched_at.isoformat() if candidate.fetched_at else datetime.now(UTC).isoformat(),
        "raw_response_hash": candidate.raw_response_hash,
        "parser_version": candidate.parser_version,
        "match_status": "COLLECTED",
        "warnings": [],
        "requested_language": requested_language,
        "provider_position": provider_position,
        "provider_page": provider_page,
        "provider_page_position": candidate.provider_position,
        "title": candidate.title,
        "original_title": candidate.original_title,
        "normalized_title": normalize_evidence_title(candidate.title),
        "original_language": candidate.original_language,
        "release_date": candidate.release_date,
        "release_year": candidate.release_year,
        "genre_ids": candidate.genre_ids,
        "popularity": candidate.popularity,
        "vote_average": candidate.vote_average,
        "vote_count": candidate.vote_count,
    }


def _load_tabular_rows(name: str, raw: bytes) -> list[dict[str, Any]]:
    if name.lower().endswith(".csv"):
        return list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    if name.lower().endswith(".json"):
        payload = json.loads(raw.decode("utf-8"))
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        if isinstance(payload, dict):
            for key in ("records", "results", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [row for row in value if isinstance(row, dict)]
        raise ValueError("json awards file must contain a list of objects")
    raise ValueError("unsupported awards file type")


def _first_text(row: dict[str, Any], keys: list[str]) -> str | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_int(row: dict[str, Any], keys: list[str]) -> int | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            digits = "".join(char for char in value if char.isdigit())
            if len(digits) >= 4:
                return int(digits[:4])
    return None


def _binding_text(binding: dict[str, Any], key: str) -> str | None:
    value = binding.get(key, {})
    if isinstance(value, dict):
        text = value.get("value")
        if isinstance(text, str) and text:
            return text
    return None


def _collect_multilingual_labels(rows: list[dict[str, Any]], value_key: str, lang_key: str) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    labels: list[dict[str, str]] = []
    for row in rows:
        value = _binding_text(row, value_key)
        language = _binding_text(row, lang_key)
        if not value or not language or (value, language) in seen:
            continue
        seen.add((value, language))
        labels.append({"value": value, "language": language, "normalized": normalize_evidence_title(value)})
    return labels


def _collect_unique_values(rows: list[dict[str, Any]], key: str) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for row in rows:
        value = _binding_text(row, key)
        if value and value not in seen:
            seen.add(value)
            values.append(value)
    return values


def _first_non_null(rows: list[dict[str, Any]], key: str) -> str | None:
    for row in rows:
        value = _binding_text(row, key)
        if value:
            return value
    return None


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _retry_delay_seconds(retry_after: str | None) -> float:
    if not retry_after:
        return 1.0
    value = retry_after.strip()
    if value.isdigit():
        return max(0.0, float(value))
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return 1.0
    now = datetime.now(UTC)
    return max(0.0, round((parsed - now).total_seconds(), 3))


def _chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _pct(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100.0, 2)


def normalize_evidence_title(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold().strip()
    cleaned = []
    for char in text:
        category = unicodedata.category(char)
        if category.startswith(("L", "N")):
            cleaned.append(char)
        else:
            cleaned.append(" ")
    return UNICODE_SPACE_RE.sub(" ", "".join(cleaned)).strip()
