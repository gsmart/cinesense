from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
import hashlib
import json
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.adapters.tmdb import (
    TmdbAdapter,
    TmdbCandidate,
    TmdbMovieBundle,
    UnsupportedTmdbDiscoverFilterError,
    summarize_tmdb_http_error,
)
from app.core.config import Settings, get_settings
from app.core.freshness import FreshnessState, FreshnessWindow, evaluate_freshness
from app.core.ranking import build_ranking_input, compute_ranking
from app.interpreters import (
    InterpreterFailureError,
    InterpreterUnavailableError,
    NaturalLanguageDiscoveryInterpreter,
)
from app.core.normalization import normalize_region, normalize_title
from app.models.movie import ExternalId, Movie, MovieAlias, Observation
from app.schemas.discovery import DiscoveryRequest
from app.schemas.natural_language import NaturalLanguageDiscoveryRequest

settings = get_settings()
logger = logging.getLogger(__name__)

def extract_genres_from_movie(movie: Movie) -> list[str]:
    title_metadata = None
    for obs in movie.observations:
        if obs.signal_type == "title_metadata" and obs.source == "tmdb":
            title_metadata = obs
            break
    if title_metadata and isinstance(title_metadata.value, dict):
        genre_ids = title_metadata.value.get("genre_ids")
        if genre_ids and isinstance(genre_ids, list):
            TMDB_GENRE_MAP = {
                28: "Action",
                12: "Adventure",
                16: "Animation",
                35: "Comedy",
                80: "Crime",
                99: "Documentary",
                18: "Drama",
                10751: "Family",
                14: "Fantasy",
                36: "History",
                27: "Horror",
                10402: "Music",
                9648: "Mystery",
                10749: "Romance",
                878: "Science Fiction",
                53: "Thriller",
                10770: "TV Movie",
                10752: "War",
                37: "Western"
            }
            mapped = [TMDB_GENRE_MAP[gid] for gid in genre_ids if gid in TMDB_GENRE_MAP]
            if mapped:
                from app.regional_cohort_baselines import _normalize_key_part
                return [_normalize_key_part(g) for g in mapped]
        genres = title_metadata.value.get("genres")
        if genres and isinstance(genres, list):
            from app.regional_cohort_baselines import _normalize_key_part
            return [_normalize_key_part(g) for g in genres if isinstance(g, str)]
    return []


def build_signal_values_for_live_movie(vote_average: float | None, vote_count: int | None, popularity: float | None) -> dict[str, Any]:
    import math
    rating_val = None
    rating_ex = None
    if vote_average is None:
        rating_ex = "missing"
    elif vote_average < 0 or vote_average > 10:
        rating_ex = "out_of_range"
        rating_val = 0.0
    else:
        rating_val = float(vote_average)

    rating_norm_val = None
    if rating_val is not None and rating_ex is None:
        rating_norm_val = round(rating_val / 10.0, 6)

    vote_val = None
    vote_ex = None
    if vote_count is None:
        vote_ex = "missing"
    elif vote_count < 0:
        vote_ex = "negative_not_allowed"
        vote_val = 0.0
    else:
        vote_val = float(vote_count)

    vote_log1p_val = None
    if vote_val is not None and vote_ex is None:
        vote_log1p_val = round(math.log1p(vote_val), 6)

    pop_val = None
    pop_ex = None
    if popularity is None:
        pop_ex = "missing"
    elif popularity < 0:
        pop_ex = "negative_not_allowed"
        pop_val = 0.0
    else:
        pop_val = float(popularity)

    pop_log1p_val = None
    if pop_val is not None and pop_ex is None:
        pop_log1p_val = round(math.log1p(pop_val), 6)

    return {
        "tmdb_rating": {"value": rating_val, "scale": "0-10", "exclusion_reason": rating_ex},
        "tmdb_rating_normalized": {"value": rating_norm_val, "scale": "0-1", "exclusion_reason": rating_ex},
        "tmdb_vote_count": {"value": vote_val, "scale": None, "exclusion_reason": vote_ex},
        "tmdb_vote_count_log1p": {"value": vote_log1p_val, "scale": None, "exclusion_reason": vote_ex},
        "tmdb_popularity": {"value": pop_val, "scale": None, "exclusion_reason": pop_ex},
        "tmdb_popularity_log1p": {"value": pop_log1p_val, "scale": None, "exclusion_reason": pop_ex},
    }


@lru_cache(maxsize=1)
def load_regional_shadow_data(artifact_root: str, run_id: str) -> dict[str, Any]:
    baseline_dir = Path(artifact_root) / run_id
    if not baseline_dir.exists():
        parent = Path(artifact_root)
        if parent.exists():
            subdirs = sorted([d for d in parent.iterdir() if d.is_dir()], key=lambda x: x.name, reverse=True)
            if subdirs:
                baseline_dir = subdirs[0]

    if not baseline_dir.exists():
        return {"error": "baseline_cohort_artifacts_not_found"}

    baselines_path = baseline_dir / "cohort_baselines.json"
    assignments_path = baseline_dir / "movie_cohort_assignments.jsonl"

    if not baselines_path.exists() or not assignments_path.exists():
        return {"error": "baseline_cohort_artifacts_not_found"}

    try:
        with open(baselines_path, "r", encoding="utf-8") as f:
            baselines = json.load(f)

        baseline_version = baselines.get("baseline_version")
        if baseline_version != "regional-cohort-baseline-v1":
            return {"error": "baseline_cohort_version_mismatch"}

        assignments = {}
        with open(assignments_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    row = json.loads(line)
                    assignments[row["tmdb_movie_id"]] = row

        cohort_records = baselines.get("cohort_records", [])
        cohort_by_key = {r["cohort_key"]: r for r in cohort_records}

        from collections import defaultdict
        from app.cine_score_v2 import CohortSignalSamples

        grouped_samples = defaultdict(lambda: defaultdict(list))
        for row in assignments.values():
            for key_name in ("level_1_cohort_key", "level_2_cohort_key", "level_3_cohort_key", "global_cohort_key"):
                cohort_key = row.get(key_name)
                if not cohort_key:
                    continue
                for signal_name in ("tmdb_rating_normalized", "tmdb_vote_count_log1p", "tmdb_popularity_log1p"):
                    val_entry = row["signal_values"].get(signal_name)
                    if val_entry and val_entry.get("value") is not None:
                        grouped_samples[cohort_key][signal_name].append(float(val_entry["value"]))

        cohort_samples = {}
        for cohort_key, values in grouped_samples.items():
            cohort_samples[cohort_key] = CohortSignalSamples(
                rating_normalized=tuple(sorted(values.get("tmdb_rating_normalized", []))),
                vote_count_log1p=tuple(sorted(values.get("tmdb_vote_count_log1p", []))),
                popularity_log1p=tuple(sorted(values.get("tmdb_popularity_log1p", []))),
            )

        baseline_hash = hashlib.sha256(baselines_path.read_bytes()).hexdigest()
        review_status = baselines.get("review_status", {}).get("status", "PENDING")
        gate_status = baselines.get("gate_status", "BLOCKED_BY_LOW_COVERAGE")
        activation_eligible = baselines.get("activation_eligible", False)
        provisional_status = "APPROVED_FOR_SHADOW" if gate_status in ("GO_FOR_ALL_LANGUAGES", "GO_FOR_LIMITED_LANGUAGES") else "PROVISIONAL_SHADOW_ONLY"

        return {
            "assignments": assignments,
            "cohort_by_key": cohort_by_key,
            "cohort_samples": cohort_samples,
            "baseline_hash": baseline_hash,
            "review_status": review_status,
            "gate_status": gate_status,
            "activation_eligible": activation_eligible,
            "provisional_status": provisional_status,
        }
    except Exception as exc:
        logger.warning("Failed to load regional shadow data: %s", exc)
        return {"error": "baseline_cohort_artifacts_load_error"}


class LookupService:
    def __init__(self, db: Session, tmdb: TmdbAdapter, settings_override: Settings | None = None) -> None:
        self.db = db
        self.tmdb = tmdb
        self.settings = settings_override or settings

    async def lookup(self, *, title: str, year: int | None, region: str | None, media_type: str, include_shadow: bool = False) -> dict:
        normalized_title = normalize_title(title)
        normalized_region = normalize_region(region)
        local_matches = self._find_local_matches(normalized_title, year, media_type)
        local_fresh = [movie for movie in local_matches if self._movie_state(movie) == FreshnessState.FRESH]
        if len(local_fresh) == 1:
            return self._resolved_payload(local_fresh[0], normalized_title, year, normalized_region, "local_cache", include_shadow=include_shadow)
        if len(local_fresh) > 1:
            return self._disambiguation_payload(local_fresh, normalized_title, normalized_region)

        local_stale_usable = [movie for movie in local_matches if self._movie_state(movie) == FreshnessState.STALE_USABLE]
        if len(local_stale_usable) == 1:
            return self._resolved_payload(local_stale_usable[0], normalized_title, year, normalized_region, "local_cache", include_shadow=include_shadow)
        if len(local_stale_usable) > 1:
            return self._disambiguation_payload(local_stale_usable, normalized_title, normalized_region)

        if not self.tmdb.enabled:
            if local_matches:
                if len(local_matches) == 1:
                    return self._resolved_payload(local_matches[0], normalized_title, year, normalized_region, "local_cache", include_shadow=include_shadow)
                return self._disambiguation_payload(local_matches, normalized_title, normalized_region)
            raise RuntimeError("TMDB token is not configured and no local data exists")

        try:
            candidates = await self.tmdb.search_titles(title, year, media_type)
        except httpx.HTTPError as exc:
            self._log_tmdb_failure("search_titles", exc, title=title, year=year, media_type=media_type)
            raise RuntimeError("TMDB request failed") from exc
        exact_candidates = self._filter_candidates(candidates, normalized_title, year)
        if len(exact_candidates) != 1:
            return self._disambiguation_candidates_payload(exact_candidates or candidates, normalized_title, normalized_region)

        try:
            movie = await self._upsert_tmdb_movie(exact_candidates[0], normalized_region)
        except httpx.HTTPError as exc:
            self._log_tmdb_failure(
                "get_movie_bundle",
                exc,
                source_movie_id=exact_candidates[0].source_movie_id,
                region=normalized_region,
            )
            raise RuntimeError("TMDB request failed") from exc
        return self._resolved_payload(movie, normalized_title, year, normalized_region, "tmdb", include_shadow=include_shadow)

    async def recommend_from_seed_movie(
        self,
        *,
        seed_movie_id: str,
        region: str | None = None,
        limit: int = 20,
        include_shadow: bool = False,
    ) -> dict:
        seed = self._find_movie_by_id(seed_movie_id)
        normalized_region = normalize_region(region)
        constrained_limit = min(max(limit, 1), 20)

        if seed is None:
            return {
                "status": "seed_not_found",
                "seed": None,
                "region": normalized_region,
                "limit": constrained_limit,
                "results": [],
            }
        if seed.media_type != "movie":
            return {
                "status": "unsupported_media_type",
                "seed": self._seed_payload(seed),
                "region": normalized_region,
                "limit": constrained_limit,
                "results": [],
            }

        external = next(
            (item for item in seed.external_ids if item.source == "tmdb" and item.media_type == "movie"),
            None,
        )
        if external is None:
            return {
                "status": "missing_external_id",
                "seed": self._seed_payload(seed),
                "region": normalized_region,
                "limit": constrained_limit,
                "results": [],
            }

        try:
            candidates = await self.tmdb.get_seed_recommendations(
                external.source_movie_id,
                constrained_limit,
                region=normalized_region,
            )
        except httpx.HTTPError as exc:
            self._log_tmdb_failure(
                "get_seed_recommendations",
                exc,
                seed_movie_id=seed_movie_id,
                tmdb_source_movie_id=external.source_movie_id,
                region=normalized_region,
                limit=constrained_limit,
            )
            raise RuntimeError("TMDB request failed") from exc

        persisted = self.persist_seed_recommendation_candidates(
            seed_source_movie_id=external.source_movie_id,
            candidates=candidates,
        )
        ranked = self.rank_seed_recommendation_candidates(persisted)[:constrained_limit]
        self._attach_shadow_comparisons(ranked, include_shadow=include_shadow)
        return {
            "status": "ok",
            "seed": self._seed_payload(seed),
            "region": normalized_region,
            "limit": constrained_limit,
            "results": ranked,
            "page": {
                "page": 1,
                "requested_page_size": constrained_limit,
                "returned_count": len(ranked),
                "max_page_size": 20,
            },
        }

    async def discover_movies(self, *, request: DiscoveryRequest) -> dict:
        try:
            candidates = await self.tmdb.discover_movies(request)
        except UnsupportedTmdbDiscoverFilterError:
            return {
                "status": "unsupported_filter",
                "unsupported_filter": "availability_required",
                "page": {
                    "page": request.page,
                    "requested_page_size": request.page_size,
                    "returned_count": 0,
                    "max_page_size": 20,
                },
                "results": [],
            }
        except httpx.HTTPError as exc:
            self._log_tmdb_failure(
                "discover_movies",
                exc,
                page=request.page,
                page_size=request.page_size,
                region=request.region,
            )
            raise RuntimeError("TMDB request failed") from exc

        persisted = self.persist_discovery_candidates(candidates=candidates)
        ranked = self.rank_discovery_candidates(persisted)[: request.page_size]
        self._attach_shadow_comparisons(ranked, include_shadow=request.include_shadow)
        return {
            "status": "ok",
            "page": {
                "page": request.page,
                "requested_page_size": request.page_size,
                "returned_count": len(ranked),
                "max_page_size": 20,
            },
            "results": ranked,
        }

    async def discover_from_natural_language(
        self,
        *,
        request: NaturalLanguageDiscoveryRequest,
        interpreter: NaturalLanguageDiscoveryInterpreter,
    ) -> dict:
        try:
            untrusted = await interpreter.interpret(request)
        except InterpreterUnavailableError:
            return {
                "status": "interpreter_unavailable",
                "query": request.query,
            }
        except InterpreterFailureError:
            return {
                "status": "interpreter_failure",
                "query": request.query,
            }
        except Exception:
            return {
                "status": "interpreter_failure",
                "query": request.query,
            }

        if isinstance(untrusted, str):
            try:
                untrusted = json.loads(untrusted)
            except json.JSONDecodeError:
                return {
                    "status": "invalid_interpretation",
                    "query": request.query,
                }

        if not isinstance(untrusted, dict):
            return {
                "status": "invalid_interpretation",
                "query": request.query,
            }

        candidate_payload = dict(untrusted)
        candidate_payload["page"] = request.page
        candidate_payload["page_size"] = request.page_size
        candidate_payload["include_shadow"] = request.include_shadow
        if getattr(request, "region", None) is not None:
            candidate_payload["region"] = request.region

        try:
            normalized_request = DiscoveryRequest.model_validate(candidate_payload)
        except Exception as exc:
            details = str(exc)
            if "unrestricted discovery requests are not allowed" in details:
                return {
                    "status": "unrestricted_interpretation",
                    "query": request.query,
                }
            return {
                "status": "invalid_interpretation",
                "query": request.query,
            }

        result = await self.discover_movies(request=normalized_request)
        result["query"] = request.query
        result["request"] = normalized_request.model_dump()
        return result

    def persist_seed_recommendation_candidates(
        self,
        *,
        seed_source_movie_id: str,
        candidates: list[TmdbCandidate],
    ) -> list[Movie]:
        return self._persist_tmdb_candidates(
            candidates=candidates,
            excluded_source_ids={seed_source_movie_id},
        )

    def persist_discovery_candidates(
        self,
        *,
        candidates: list[TmdbCandidate],
    ) -> list[Movie]:
        return self._persist_tmdb_candidates(candidates=candidates, excluded_source_ids=set())

    def rank_seed_recommendation_candidates(self, movies: list[Movie]) -> list[dict]:
        return self._rank_tmdb_candidates(
            movies,
            match_value_for_position=lambda position: (20 - position) / 20.0,
        )

    def rank_discovery_candidates(self, movies: list[Movie]) -> list[dict]:
        return self._rank_tmdb_candidates(
            movies,
            match_value_for_position=lambda _position: 1.0,
        )

    def _persist_tmdb_candidates(
        self,
        *,
        candidates: list[TmdbCandidate],
        excluded_source_ids: set[str],
    ) -> list[Movie]:
        if not candidates:
            return []

        persisted: list[Movie] = []
        seen_source_ids: set[str] = set()
        for candidate in candidates:
            if len(persisted) >= 20:
                break
            if candidate.media_type != "movie":
                continue
            if candidate.source_movie_id in excluded_source_ids or candidate.source_movie_id in seen_source_ids:
                continue
            seen_source_ids.add(candidate.source_movie_id)
            persisted.append(self._upsert_tmdb_recommendation_candidate(candidate))
        return persisted

    def _rank_tmdb_candidates(self, movies: list[Movie], *, match_value_for_position) -> list[dict]:
        if not movies:
            return []

        ranked: list[dict] = []
        for position, movie in enumerate(movies[:20]):
            external = next((item for item in movie.external_ids if item.source == "tmdb"), None)
            if external is None:
                continue

            signal_map = {observation.signal_type: observation for observation in movie.observations if observation.source == "tmdb"}
            audience = signal_map.get("audience_reception")
            popularity = signal_map.get("popularity")
            freshness_summary: dict[str, str] = {}
            for signal_name in ("audience_reception", "popularity"):
                observation = signal_map.get(signal_name)
                freshness_summary[signal_name] = self._observation_state(observation).value
            freshness_summary["critic_consensus"] = FreshnessState.MISSING.value

            missing_signals = ["critic_consensus"]
            if audience is None:
                missing_signals.append("audience_reception")
            if popularity is None:
                missing_signals.append("popularity")

            ranking_input = build_ranking_input(
                normalized_query="",
                canonical_title=movie.normalized_title,
                release_year=movie.release_year,
                requested_year=None,
                vote_average=float(audience.numeric_value) if audience and audience.numeric_value is not None else None,
                vote_count=audience.evidence_count if audience else None,
                popularity=float(popularity.numeric_value) if popularity and popularity.numeric_value is not None else None,
                missing_signals=missing_signals,
                freshness=freshness_summary,
                seed_relevance=match_value_for_position(position),
                tmdb_source_movie_id=external.source_movie_id,
                provider_position=position,
            )
            computation = compute_ranking(
                ranking_input,
                requested_version=self.settings.active_ranking_version,
                settings=self.settings,
            )
            ranked.append(
                {
                    "movie": {
                        "movie_id": str(movie.id),
                        "canonical_title": movie.canonical_title,
                        "release_year": movie.release_year,
                        "media_type": movie.media_type,
                        "original_language": movie.original_language,
                        "overview": movie.overview,
                        "poster_url": movie.poster_url,
                    },
                    "tmdb_source_movie_id": external.source_movie_id,
                    "provider_position": position,
                    "score": computation.total,
                    "score_version": computation.applied_ranking_version,
                    "score_components": computation.components,
                    "missing_signals": computation.missing_signals,
                    "provenance": {
                        "source": external.source,
                        "source_movie_id": external.source_movie_id,
                        "source_url": external.source_url,
                    },
                    "freshness": freshness_summary,
                }
            )

        ranked.sort(key=lambda item: (-item["score"], item["provider_position"], item["tmdb_source_movie_id"]))
        return ranked

    def _find_local_matches(self, normalized_title: str, year: int | None, media_type: str) -> list[Movie]:
        stmt: Select[tuple[Movie]] = (
            select(Movie)
            .join(MovieAlias)
            .options(
                joinedload(Movie.aliases),
                joinedload(Movie.external_ids),
                joinedload(Movie.observations),
            )
            .where(MovieAlias.normalized_alias == normalized_title, Movie.media_type == media_type)
        )
        if year is not None:
            stmt = stmt.where(Movie.release_year == year)
        return list(self.db.scalars(stmt).unique())

    def _log_tmdb_failure(self, operation: str, exc: httpx.HTTPError, **context: object) -> None:
        category, detail = summarize_tmdb_http_error(exc)
        logger.warning(
            "TMDB operation failed: operation=%s category=%s detail=%s context=%s",
            operation,
            category,
            detail,
            context,
        )

    def _find_movie_by_id(self, movie_id: str) -> Movie | None:
        try:
            parsed_id = UUID(movie_id)
        except ValueError:
            return None
        return self.db.scalar(
            select(Movie)
            .options(joinedload(Movie.aliases), joinedload(Movie.external_ids), joinedload(Movie.observations))
            .where(Movie.id == parsed_id)
        )

    def _seed_payload(self, movie: Movie) -> dict:
        return {
            "movie_id": str(movie.id),
            "canonical_title": movie.canonical_title,
            "release_year": movie.release_year,
            "media_type": movie.media_type,
        }

    def _movie_state(self, movie: Movie) -> FreshnessState:
        metadata = self._find_observation(movie, "title_metadata")
        if metadata is None:
            return FreshnessState.MISSING
        return evaluate_freshness(
            FreshnessWindow(metadata.fresh_until, metadata.stale_until, metadata.fetch_status)
        )

    def _find_observation(self, movie: Movie, signal_type: str) -> Observation | None:
        for observation in movie.observations:
            if observation.signal_type == signal_type:
                return observation
        return None

    def _observation_state(self, observation: Observation | None) -> FreshnessState:
        if observation is None:
            return FreshnessState.MISSING
        now = datetime.now(UTC)
        if observation.fresh_until is not None and observation.fresh_until.tzinfo is None:
            now = now.replace(tzinfo=None)
        return evaluate_freshness(
            FreshnessWindow(observation.fresh_until, observation.stale_until, observation.fetch_status),
            now,
        )

    def _filter_candidates(
        self, candidates: list[TmdbCandidate], normalized_title: str, year: int | None
    ) -> list[TmdbCandidate]:
        matches = [candidate for candidate in candidates if candidate.normalized_title == normalized_title]
        if year is not None:
            year_matches = [candidate for candidate in matches if candidate.release_year == year]
            if year_matches:
                return year_matches
        return matches

    async def _upsert_tmdb_movie(self, candidate: TmdbCandidate, region: str | None) -> Movie:
        existing = self._find_tmdb_movie_by_source_id(candidate.source_movie_id)
        if existing and self._movie_state(existing) in {FreshnessState.FRESH, FreshnessState.STALE_USABLE}:
            return existing

        bundle = await self.tmdb.get_movie_bundle(candidate.source_movie_id, region)
        if existing is None:
            existing = Movie(
                canonical_title=bundle.canonical_title,
                normalized_title=bundle.normalized_title,
                release_year=bundle.release_year,
                media_type="movie",
                original_language=bundle.original_language,
                overview=bundle.overview,
                runtime_minutes=bundle.runtime_minutes,
                poster_url=bundle.poster_url,
            )
            self.db.add(existing)
            self.db.flush()

        existing.canonical_title = bundle.canonical_title
        existing.normalized_title = bundle.normalized_title
        existing.release_year = bundle.release_year
        existing.original_language = bundle.original_language
        existing.overview = bundle.overview
        existing.runtime_minutes = bundle.runtime_minutes
        existing.poster_url = bundle.poster_url
        self._merge_aliases(existing, bundle.aliases)
        self._merge_external_id(existing, bundle)
        self._merge_observations(existing, bundle)

        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            recovered = self._find_tmdb_movie_by_source_id(candidate.source_movie_id)
            if recovered is None:
                raise
            return recovered
        self.db.refresh(existing)
        return existing

    def _upsert_tmdb_recommendation_candidate(self, candidate: TmdbCandidate) -> Movie:
        existing = self._find_tmdb_movie_by_source_id(candidate.source_movie_id)
        if existing is None:
            existing = Movie(
                canonical_title=candidate.title,
                normalized_title=candidate.normalized_title,
                release_year=candidate.release_year,
                media_type="movie",
                original_language=candidate.original_language,
                overview=candidate.overview,
                runtime_minutes=None,
                poster_url=self._candidate_poster_url(candidate),
            )
            self.db.add(existing)
            self.db.flush()

        existing.canonical_title = candidate.title
        existing.normalized_title = candidate.normalized_title
        existing.release_year = candidate.release_year
        existing.media_type = "movie"
        existing.original_language = candidate.original_language
        existing.overview = candidate.overview
        existing.poster_url = self._candidate_poster_url(candidate)
        self._merge_aliases(existing, [candidate.title])
        self._merge_candidate_external_id(existing, candidate)
        self._merge_candidate_observations(existing, candidate)

        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            recovered = self._find_tmdb_movie_by_source_id(candidate.source_movie_id)
            if recovered is None:
                raise
            return recovered
        self.db.refresh(existing)
        return existing

    def _find_tmdb_movie_by_source_id(self, source_movie_id: str) -> Movie | None:
        return self.db.scalar(
            select(Movie)
            .join(ExternalId)
            .options(joinedload(Movie.aliases), joinedload(Movie.external_ids), joinedload(Movie.observations))
            .where(ExternalId.source == "tmdb", ExternalId.source_movie_id == source_movie_id)
        )

    def _candidate_poster_url(self, candidate: TmdbCandidate) -> str | None:
        if not candidate.poster_path:
            return None
        return f"{settings.base_image_url}{candidate.poster_path}"

    def _merge_aliases(self, movie: Movie, aliases: list[str]) -> None:
        known = {alias.normalized_alias for alias in movie.aliases}
        for alias in aliases:
            normalized = normalize_title(alias)
            if normalized in known:
                continue
            movie.aliases.append(MovieAlias(alias=alias, normalized_alias=normalized, kind="title"))
            known.add(normalized)

    def _merge_external_id(self, movie: Movie, bundle: TmdbMovieBundle) -> None:
        now = datetime.now(UTC)
        for external in movie.external_ids:
            if external.source == "tmdb" and external.source_movie_id == bundle.source_movie_id:
                external.source_url = bundle.source_url
                external.last_seen_at = now
                return
        movie.external_ids.append(
            ExternalId(
                source="tmdb",
                source_movie_id=bundle.source_movie_id,
                media_type="movie",
                source_url=bundle.source_url,
                first_seen_at=now,
                last_seen_at=now,
            )
        )

    def _merge_candidate_external_id(self, movie: Movie, candidate: TmdbCandidate) -> None:
        now = datetime.now(UTC)
        for external in movie.external_ids:
            if external.source == "tmdb" and external.source_movie_id == candidate.source_movie_id:
                external.source_url = candidate.source_url
                external.last_seen_at = now
                return
        movie.external_ids.append(
            ExternalId(
                source="tmdb",
                source_movie_id=candidate.source_movie_id,
                media_type="movie",
                source_url=candidate.source_url,
                first_seen_at=now,
                last_seen_at=now,
            )
        )

    def _merge_candidate_observations(self, movie: Movie, candidate: TmdbCandidate) -> None:
        observation_items = self._candidate_observation_items(candidate)
        if not observation_items:
            return
        bundle = TmdbMovieBundle(
            source_movie_id=candidate.source_movie_id,
            source_url=candidate.source_url or f"https://www.themoviedb.org/movie/{candidate.source_movie_id}",
            canonical_title=candidate.title,
            normalized_title=candidate.normalized_title,
            release_year=candidate.release_year,
            original_language=candidate.original_language,
            overview=candidate.overview,
            runtime_minutes=None,
            poster_url=self._candidate_poster_url(candidate),
            aliases=[candidate.title],
            observations=observation_items,
        )
        self._merge_observations(movie, bundle)

    def _candidate_observation_items(self, candidate: TmdbCandidate) -> list[dict]:
        if candidate.fetched_at is None or candidate.raw_response_hash is None:
            return []

        source_url = candidate.source_url or f"https://www.themoviedb.org/movie/{candidate.source_movie_id}"
        items: list[dict] = []
        if isinstance(candidate.popularity, int | float):
            items.append(
                self._observation_item(
                    signal_type="popularity",
                    value={"popularity": candidate.popularity},
                    fetched_at=candidate.fetched_at,
                    raw_hash=candidate.raw_response_hash,
                    source_movie_id=candidate.source_movie_id,
                    source_url=source_url,
                    fresh_delta=timedelta(hours=settings.popularity_fresh_hours),
                    stale_delta=timedelta(days=settings.popularity_stale_days),
                    numeric_value=float(candidate.popularity),
                    scale=None,
                )
            )
        if isinstance(candidate.vote_average, int | float):
            items.append(
                self._observation_item(
                    signal_type="audience_reception",
                    value={"vote_average": candidate.vote_average, "vote_count": candidate.vote_count},
                    fetched_at=candidate.fetched_at,
                    raw_hash=candidate.raw_response_hash,
                    source_movie_id=candidate.source_movie_id,
                    source_url=source_url,
                    fresh_delta=timedelta(days=settings.rating_fresh_days),
                    stale_delta=timedelta(days=settings.rating_stale_days),
                    numeric_value=float(candidate.vote_average),
                    evidence_count=candidate.vote_count if isinstance(candidate.vote_count, int) else None,
                    scale=candidate.rating_scale,
                )
            )
        # Add title_metadata observation with genre_ids if present
        if candidate.genre_ids:
            items.append(
                self._observation_item(
                    signal_type="title_metadata",
                    value={
                        "title": candidate.title,
                        "original_title": candidate.original_title,
                        "release_date": candidate.release_date,
                        "region": None,
                        "genre_ids": candidate.genre_ids,
                    },
                    fetched_at=candidate.fetched_at,
                    raw_hash=candidate.raw_response_hash,
                    source_movie_id=candidate.source_movie_id,
                    source_url=source_url,
                    fresh_delta=timedelta(days=settings.metadata_fresh_days),
                    stale_delta=timedelta(days=settings.metadata_stale_days),
                )
            )
        for item in items:
            item["fetch_status"] = candidate.fetch_status
            item["parser_version"] = candidate.parser_version
        return items

    def _observation_item(
        self,
        *,
        signal_type: str,
        value: dict,
        fetched_at: datetime,
        raw_hash: str,
        source_movie_id: str,
        source_url: str,
        fresh_delta: timedelta,
        stale_delta: timedelta,
        numeric_value: float | None = None,
        evidence_count: int | None = None,
        scale: str | None = None,
    ) -> dict:
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

    def _merge_observations(self, movie: Movie, bundle: TmdbMovieBundle) -> None:
        by_signal = {observation.signal_type: observation for observation in movie.observations if observation.source == "tmdb"}
        for item in bundle.observations:
            observation = by_signal.get(item["signal_type"])
            if observation is None:
                movie.observations.append(
                    Observation(
                        source="tmdb",
                        source_movie_id=item["source_movie_id"],
                        signal_type=item["signal_type"],
                        value=item["value"],
                        scale=item["scale"],
                        evidence_count=item["evidence_count"],
                        numeric_value=item["numeric_value"],
                        fetched_at=item["fetched_at"],
                        fresh_until=item["fresh_until"],
                        stale_until=item["stale_until"],
                        last_success_at=item["last_success_at"],
                        source_url=item["source_url"],
                        fetch_status=item["fetch_status"],
                        parser_version=item["parser_version"],
                        raw_response_hash=item["raw_response_hash"],
                    )
                )
                continue
            observation.value = item["value"]
            observation.scale = item["scale"]
            observation.evidence_count = item["evidence_count"]
            observation.numeric_value = item["numeric_value"]
            observation.fetched_at = item["fetched_at"]
            observation.fresh_until = item["fresh_until"]
            observation.stale_until = item["stale_until"]
            observation.last_success_at = item["last_success_at"]
            observation.source_url = item["source_url"]
            observation.fetch_status = item["fetch_status"]
            observation.parser_version = item["parser_version"]
            observation.raw_response_hash = item["raw_response_hash"]

    def _resolved_payload(
        self, movie: Movie, normalized_title: str, year: int | None, region: str | None, source: str, include_shadow: bool = False
    ) -> dict:
        observations = []
        freshness_summary: dict[str, str] = {}
        signal_map = {}
        for observation in movie.observations:
            state = evaluate_freshness(
                FreshnessWindow(observation.fresh_until, observation.stale_until, observation.fetch_status)
            )
            freshness_summary[observation.signal_type] = state.value
            signal_map[observation.signal_type] = observation
            numeric = float(observation.numeric_value) if isinstance(observation.numeric_value, Decimal) else observation.numeric_value
            observations.append(
                {
                    "signal_type": observation.signal_type,
                    "source": observation.source,
                    "fetched_at": observation.fetched_at,
                    "fresh_until": observation.fresh_until,
                    "stale_until": observation.stale_until,
                    "freshness_state": state.value,
                    "value": observation.value,
                    "scale": observation.scale,
                    "evidence_count": observation.evidence_count,
                    "source_url": observation.source_url,
                    "fetch_status": observation.fetch_status,
                    "numeric_value": numeric,
                }
            )

        missing_signals = [
            signal
            for signal in ["audience_reception", "critic_consensus", "popularity"]
            if signal not in signal_map
        ]
        audience = signal_map.get("audience_reception")
        popularity = signal_map.get("popularity")
        external = next((item for item in movie.external_ids if item.source == "tmdb"), None)
        ranking_input = build_ranking_input(
            normalized_query=normalized_title,
            canonical_title=movie.normalized_title,
            release_year=movie.release_year,
            requested_year=year,
            vote_average=float(audience.numeric_value) if audience and audience.numeric_value is not None else None,
            vote_count=audience.evidence_count if audience else None,
            popularity=float(popularity.numeric_value) if popularity and popularity.numeric_value is not None else None,
            missing_signals=missing_signals,
            freshness=freshness_summary,
            tmdb_source_movie_id=external.source_movie_id if external else None,
        )
        computation = compute_ranking(
            ranking_input,
            requested_version=self.settings.active_ranking_version,
            settings=self.settings,
        )
        res = {
            "status": "resolved",
            "normalized_title": normalized_title,
            "region": region,
            "media_type": "movie",
            "source": source,
            "movie": {
                "movie_id": str(movie.id),
                "canonical_title": movie.canonical_title,
                "release_year": movie.release_year,
                "media_type": movie.media_type,
                "original_language": movie.original_language,
                "overview": movie.overview,
                "runtime_minutes": movie.runtime_minutes,
                "poster_url": movie.poster_url,
                "aliases": sorted({alias.alias for alias in movie.aliases}),
                "source": "tmdb" if external else "local_cache",
                "source_movie_id": external.source_movie_id if external else "",
                "source_url": external.source_url if external else None,
                "freshness": freshness_summary,
                "observations": observations,
                "missing_signals": missing_signals,
                "score": computation.public_score(),
            },
            "disambiguation_choices": [],
        }
        self._attach_shadow_comparisons([res], include_shadow=include_shadow)
        return res

    def _disambiguation_payload(self, movies: list[Movie], normalized_title: str, region: str | None) -> dict:
        choices = []
        for movie in movies:
            external = next((item for item in movie.external_ids if item.source == "tmdb"), None)
            choices.append(
                {
                    "movie_id": str(movie.id),
                    "title": movie.canonical_title,
                    "release_year": movie.release_year,
                    "source": external.source if external else "local_cache",
                    "source_movie_id": external.source_movie_id if external else "",
                }
            )
        return {
            "status": "disambiguation",
            "normalized_title": normalized_title,
            "region": region,
            "media_type": "movie",
            "source": "local_cache",
            "movie": None,
            "disambiguation_choices": sorted(choices, key=lambda item: (item["release_year"] or 0, item["title"])),
        }

    def _disambiguation_candidates_payload(
        self, candidates: list[TmdbCandidate], normalized_title: str, region: str | None
    ) -> dict:
        deduped = []
        seen = set()
        for candidate in candidates:
            key = (candidate.source_movie_id, candidate.title, candidate.release_year)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(
                {
                    "movie_id": candidate.source_movie_id,
                    "title": candidate.title,
                    "release_year": candidate.release_year,
                    "source": "tmdb",
                    "source_movie_id": candidate.source_movie_id,
                }
            )
        return {
            "status": "disambiguation",
            "normalized_title": normalized_title,
            "region": region,
            "media_type": "movie",
            "source": "tmdb",
            "movie": None,
            "disambiguation_choices": deduped[:5],
        }

    def _attach_shadow_comparisons(self, results: list[dict], include_shadow: bool) -> None:
        if not include_shadow or not self.settings.cinesense_enable_shadow_diagnostics:
            return

        shadow_data = load_regional_shadow_data(
            self.settings.cinesense_shadow_artifact_root,
            self.settings.cinesense_shadow_run_id
        )

        v2_scores = []
        for item in results:
            tmdb_id = item.get("tmdb_source_movie_id")
            if not tmdb_id:
                movie_obj = item.get("movie")
                if movie_obj:
                    tmdb_id = item.get("source_movie_id") or movie_obj.get("source_movie_id")

            v2_score = None
            ineligible_reason = None
            assignment = None
            error_status = shadow_data.get("error") if shadow_data else "baseline_cohort_artifacts_not_found"
            if error_status:
                if error_status == "baseline_cohort_version_mismatch":
                    raise ValueError("baseline_cohort_version_mismatch")
                elif error_status == "baseline_cohort_artifacts_not_found":
                    ineligible_reason = "baseline_artifacts_not_found"
                elif error_status == "baseline_cohort_artifacts_load_error":
                    ineligible_reason = "baseline_artifacts_load_error"
                else:
                    ineligible_reason = error_status
            elif not tmdb_id:
                ineligible_reason = "insufficient_live_signals"
            else:
                movie_db = self._find_tmdb_movie_by_source_id(tmdb_id)
                if not movie_db:
                    ineligible_reason = "insufficient_live_signals"
                else:
                    from app.regional_cohort_baselines import assign_runtime_cohort, build_cohort_key, GLOBAL_COHORT_KEY

                    entity_resolution_status = "VALIDATED_EXACT_MATCH"
                    review_decision = None
                    if shadow_data and "assignments" in shadow_data:
                        saved_assignment = shadow_data["assignments"].get(tmdb_id)
                        if saved_assignment:
                            entity_resolution_status = saved_assignment.get("entity_resolution_status") or "VALIDATED_EXACT_MATCH"
                            review_decision = saved_assignment.get("review_decision")

                    # Extract observations
                    audience = None
                    popularity = None
                    for obs in movie_db.observations:
                        if obs.source == "tmdb":
                            if obs.signal_type == "audience_reception":
                                audience = obs
                            elif obs.signal_type == "popularity":
                                popularity = obs

                    vote_average = float(audience.numeric_value) if audience and audience.numeric_value is not None else None
                    vote_count = audience.evidence_count if audience else None
                    popularity_value = float(popularity.numeric_value) if popularity and popularity.numeric_value is not None else None

                    # Build signal values
                    sig_vals = build_signal_values_for_live_movie(vote_average, vote_count, popularity_value)

                    # Extract language and release year and genre
                    language = movie_db.original_language
                    release_year = movie_db.release_year
                    genres = extract_genres_from_movie(movie_db)
                    primary_genre = genres[0] if genres else None

                    available_cohorts = shadow_data.get("cohort_by_key", {})

                    cohort_assignment = assign_runtime_cohort(
                        language=language,
                        release_year=release_year,
                        primary_genre=primary_genre,
                        available_cohorts=available_cohorts,
                    )

                    if cohort_assignment.failure_reason:
                        ineligible_reason = cohort_assignment.failure_reason
                    elif (sig_vals["tmdb_rating_normalized"]["value"] is None and
                          sig_vals["tmdb_vote_count_log1p"]["value"] is None and
                          sig_vals["tmdb_popularity_log1p"]["value"] is None):
                        ineligible_reason = "insufficient_live_signals"
                    else:
                        assignment = {
                            "tmdb_movie_id": tmdb_id,
                            "original_language": cohort_assignment.normalized_language,
                            "release_year": release_year,
                            "era": cohort_assignment.normalized_era,
                            "primary_genre": cohort_assignment.normalized_genre,
                            "level_1_cohort_key": cohort_assignment.requested_cohort_key,
                            "level_2_cohort_key": build_cohort_key(level="level_2", language=cohort_assignment.normalized_language, era=cohort_assignment.normalized_era, primary_genre=cohort_assignment.normalized_genre) if cohort_assignment.normalized_language else None,
                            "level_3_cohort_key": build_cohort_key(level="level_3", language=cohort_assignment.normalized_language, era=cohort_assignment.normalized_era, primary_genre=cohort_assignment.normalized_genre) if cohort_assignment.normalized_language else None,
                            "global_cohort_key": GLOBAL_COHORT_KEY,
                            "selected_eligible_cohort_key": cohort_assignment.selected_cohort_key,
                            "selected_eligible_cohort_level": cohort_assignment.selected_cohort_level,
                            "entity_resolution_status": entity_resolution_status,
                            "review_decision": review_decision,
                            "signal_values": sig_vals,
                        }

                        selected_key = assignment.get("selected_eligible_cohort_key")
                        cohort_record = shadow_data.get("cohort_by_key", {}).get(selected_key) if selected_key else None
                        cohort_samples = shadow_data.get("cohort_samples", {}).get(selected_key) if selected_key else None
                        try:
                            from app.cine_score_v2 import compute_cine_score_v2_shadow
                            v2_res = compute_cine_score_v2_shadow(
                                assignment=assignment,
                                cohort_record=cohort_record,
                                cohort_samples=cohort_samples,
                                baseline_hash=shadow_data["baseline_hash"],
                                provisional_status=shadow_data["provisional_status"],
                                activation_eligible=shadow_data["activation_eligible"],
                            )
                            v2_score = v2_res.get("display_total")
                            if v2_score is None:
                                ineligible_reason = "insufficient_live_signals"
                        except Exception as exc:
                            logger.warning("Failed to compute v2 shadow score: %s", exc)
                            v2_score = None
                            ineligible_reason = "insufficient_live_signals"

            v2_scores.append((v2_score, ineligible_reason, assignment))

        indexed_v2 = []
        for idx, (v2_score, _, _) in enumerate(v2_scores):
            if v2_score is not None:
                indexed_v2.append((idx, v2_score))

        indexed_v2.sort(key=lambda x: (-x[1], x[0]))

        v2_ranks = {}
        for rank_idx, (orig_idx, _) in enumerate(indexed_v2, start=1):
            v2_ranks[orig_idx] = rank_idx

        for idx, item in enumerate(results):
            v2_score, ineligible_reason, assignment = v2_scores[idx]
            v1_score = item.get("score")
            if v1_score is None:
                movie_obj = item.get("movie")
                if movie_obj:
                    score_obj = movie_obj.get("score")
                    if score_obj:
                        v1_score = score_obj.get("total")

            v1_rank = idx + 1
            v2_rank = v2_ranks.get(idx)
            rank_movement = v1_rank - v2_rank if v2_rank is not None else None
            score_delta = round(v2_score - v1_score, 2) if (v2_score is not None and v1_score is not None) else None

            evidence_gate = shadow_data.get("gate_status") if shadow_data else None
            review_status = (shadow_data.get("review_status") if shadow_data else "PENDING") or "PENDING"
            activation_eligible = bool(shadow_data.get("activation_eligible")) if (shadow_data and shadow_data.get("activation_eligible") is not None) else False

            comp = {
                "authoritative": False,
                "shadow_only": True,
                "v1_score": v1_score,
                "v2_score": v2_score,
                "v1_rank": v1_rank if len(results) > 1 else None,
                "v2_rank": v2_rank,
                "rank_movement": rank_movement,
                "score_delta": score_delta,
                "score_version": "cine-score-v2-shadow-1",
                "evidence_gate": evidence_gate,
                "review_status": review_status,
                "activation_eligible": activation_eligible,
                "ineligible_reason": ineligible_reason,
                "warnings": [],
            }

            if "movie" in item:
                if isinstance(item["movie"], dict):
                    item["movie"]["shadow_comparison"] = comp
            else:
                item["shadow_comparison"] = comp
