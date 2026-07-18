from datetime import UTC, datetime
from decimal import Decimal

import httpx
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.adapters.tmdb import TmdbAdapter, TmdbCandidate, TmdbMovieBundle
from app.core.config import get_settings
from app.core.freshness import FreshnessState, FreshnessWindow, evaluate_freshness
from app.core.normalization import normalize_region, normalize_title
from app.core.scoring import compute_cine_score_v1
from app.models.movie import ExternalId, Movie, MovieAlias, Observation

settings = get_settings()


class LookupService:
    def __init__(self, db: Session, tmdb: TmdbAdapter) -> None:
        self.db = db
        self.tmdb = tmdb

    async def lookup(self, *, title: str, year: int | None, region: str | None, media_type: str) -> dict:
        normalized_title = normalize_title(title)
        normalized_region = normalize_region(region)
        local_matches = self._find_local_matches(normalized_title, year, media_type)
        local_fresh = [movie for movie in local_matches if self._movie_state(movie) == FreshnessState.FRESH]
        if len(local_fresh) == 1:
            return self._resolved_payload(local_fresh[0], normalized_title, year, normalized_region, "local_cache")
        if len(local_fresh) > 1:
            return self._disambiguation_payload(local_fresh, normalized_title, normalized_region)

        local_stale_usable = [movie for movie in local_matches if self._movie_state(movie) == FreshnessState.STALE_USABLE]
        if len(local_stale_usable) == 1:
            return self._resolved_payload(local_stale_usable[0], normalized_title, year, normalized_region, "local_cache")
        if len(local_stale_usable) > 1:
            return self._disambiguation_payload(local_stale_usable, normalized_title, normalized_region)

        if not self.tmdb.enabled:
            if local_matches:
                if len(local_matches) == 1:
                    return self._resolved_payload(local_matches[0], normalized_title, year, normalized_region, "local_cache")
                return self._disambiguation_payload(local_matches, normalized_title, normalized_region)
            raise RuntimeError("TMDB token is not configured and no local data exists")

        try:
            candidates = await self.tmdb.search_titles(title, year, media_type)
        except httpx.HTTPError as exc:
            raise RuntimeError("TMDB request failed") from exc
        exact_candidates = self._filter_candidates(candidates, normalized_title, year)
        if len(exact_candidates) != 1:
            return self._disambiguation_candidates_payload(exact_candidates or candidates, normalized_title, normalized_region)

        try:
            movie = await self._upsert_tmdb_movie(exact_candidates[0], normalized_region)
        except httpx.HTTPError as exc:
            raise RuntimeError("TMDB request failed") from exc
        return self._resolved_payload(movie, normalized_title, year, normalized_region, "tmdb")

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
        existing = self.db.scalar(
            select(Movie)
            .join(ExternalId)
            .options(joinedload(Movie.aliases), joinedload(Movie.external_ids), joinedload(Movie.observations))
            .where(ExternalId.source == "tmdb", ExternalId.source_movie_id == candidate.source_movie_id)
        )
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
            recovered = self.db.scalar(
                select(Movie)
                .join(ExternalId)
                .options(joinedload(Movie.aliases), joinedload(Movie.external_ids), joinedload(Movie.observations))
                .where(ExternalId.source == "tmdb", ExternalId.source_movie_id == candidate.source_movie_id)
            )
            if recovered is None:
                raise
            return recovered
        self.db.refresh(existing)
        return existing

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
        self, movie: Movie, normalized_title: str, year: int | None, region: str | None, source: str
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
        score = compute_cine_score_v1(
            normalized_query=normalized_title,
            canonical_title=movie.normalized_title,
            release_year=movie.release_year,
            requested_year=year,
            vote_average=float(audience.numeric_value) if audience and audience.numeric_value is not None else None,
            vote_count=audience.evidence_count if audience else None,
            popularity=float(popularity.numeric_value) if popularity and popularity.numeric_value is not None else None,
            missing_signals=missing_signals,
        )
        return {
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
                "score": score,
            },
            "disambiguation_choices": [],
        }

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
