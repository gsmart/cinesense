from datetime import UTC, datetime, timedelta
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

    def persist_seed_recommendation_candidates(
        self,
        *,
        seed_source_movie_id: str,
        candidates: list[TmdbCandidate],
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
            if candidate.source_movie_id == seed_source_movie_id or candidate.source_movie_id in seen_source_ids:
                continue
            seen_source_ids.add(candidate.source_movie_id)
            persisted.append(self._upsert_tmdb_recommendation_candidate(candidate))
        return persisted

    def rank_seed_recommendation_candidates(self, movies: list[Movie]) -> list[dict]:
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

            score = compute_cine_score_v1(
                normalized_query="",
                canonical_title=movie.normalized_title,
                release_year=movie.release_year,
                requested_year=None,
                vote_average=float(audience.numeric_value) if audience and audience.numeric_value is not None else None,
                vote_count=audience.evidence_count if audience else None,
                popularity=float(popularity.numeric_value) if popularity and popularity.numeric_value is not None else None,
                missing_signals=missing_signals,
                seed_relevance=(20 - position) / 20.0,
            )
            ranked.append(
                {
                    "movie": {
                        "movie_id": str(movie.id),
                        "canonical_title": movie.canonical_title,
                        "release_year": movie.release_year,
                        "media_type": movie.media_type,
                    },
                    "tmdb_source_movie_id": external.source_movie_id,
                    "provider_position": position,
                    "score": score["total"],
                    "score_version": score["version"],
                    "score_components": score["components"],
                    "missing_signals": score["missing_signals"],
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
        return evaluate_freshness(
            FreshnessWindow(observation.fresh_until, observation.stale_until, observation.fetch_status)
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
