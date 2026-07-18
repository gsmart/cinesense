import uuid
from datetime import UTC, datetime, timedelta

from app.models.movie import ExternalId, Movie, Observation
from app.services import LookupService


class DummyTmdb:
    enabled = True


class DummySession:
    pass


def make_movie(
    source_movie_id: str,
    title: str,
    *,
    vote_average: float | None = None,
    vote_count: int | None = None,
    popularity: float | None = None,
) -> Movie:
    movie = Movie(
        id=uuid.uuid4(),
        canonical_title=title,
        normalized_title=title.lower(),
        release_year=2000,
        media_type="movie",
        original_language="en",
        overview="x",
        runtime_minutes=None,
        poster_url=None,
    )
    movie.external_ids = [
        ExternalId(
            source="tmdb",
            source_movie_id=source_movie_id,
            media_type="movie",
            source_url=f"https://www.themoviedb.org/movie/{source_movie_id}",
        )
    ]
    movie.observations = []
    now = datetime(2026, 7, 18, tzinfo=UTC)
    if vote_average is not None:
        movie.observations.append(
            Observation(
                source="tmdb",
                source_movie_id=source_movie_id,
                signal_type="audience_reception",
                value={"vote_average": vote_average, "vote_count": vote_count},
                scale="0-10",
                evidence_count=vote_count,
                numeric_value=vote_average,
                fetched_at=now,
                fresh_until=now + timedelta(days=7),
                stale_until=now + timedelta(days=30),
                last_success_at=now,
                source_url=f"https://www.themoviedb.org/movie/{source_movie_id}",
                fetch_status="SUCCESS",
                parser_version="tmdb-v1",
                raw_response_hash="aud",
            )
        )
    if popularity is not None:
        movie.observations.append(
            Observation(
                source="tmdb",
                source_movie_id=source_movie_id,
                signal_type="popularity",
                value={"popularity": popularity},
                scale=None,
                evidence_count=None,
                numeric_value=popularity,
                fetched_at=now,
                fresh_until=now + timedelta(hours=24),
                stale_until=now + timedelta(days=7),
                last_success_at=now,
                source_url=f"https://www.themoviedb.org/movie/{source_movie_id}",
                fetch_status="SUCCESS",
                parser_version="tmdb-v1",
                raw_response_hash="pop",
            )
        )
    return movie


def test_rank_seed_recommendation_candidates_derives_seed_relevance_from_provider_position():
    service = LookupService(DummySession(), DummyTmdb())
    ranked = service.rank_seed_recommendation_candidates(
        [
            make_movie("101", "First"),
            make_movie("102", "Second"),
            make_movie("103", "Third"),
        ]
    )

    by_id = {item["tmdb_source_movie_id"]: item for item in ranked}
    assert by_id["101"]["provider_position"] == 0
    assert by_id["101"]["score_components"]["query_match"] == 30.0
    assert by_id["102"]["provider_position"] == 1
    assert by_id["102"]["score_components"]["query_match"] == 28.5
    assert by_id["103"]["provider_position"] == 2
    assert by_id["103"]["score_components"]["query_match"] == 27.0


def test_rank_seed_recommendation_candidates_uses_existing_scorer_components():
    service = LookupService(DummySession(), DummyTmdb())
    ranked = service.rank_seed_recommendation_candidates([make_movie("101", "Heat", vote_average=8.0, vote_count=1000, popularity=50.0)])
    result = ranked[0]

    assert result["score_version"] == "cine-score-v1"
    assert result["score_components"]["audience_reception"] == 20.0
    assert result["score_components"]["popularity"] == 5.0
    assert result["score_components"]["evidence_confidence"] is not None


def test_rank_seed_recommendation_candidates_higher_total_ranks_first():
    service = LookupService(DummySession(), DummyTmdb())
    ranked = service.rank_seed_recommendation_candidates(
        [
            make_movie("101", "Low", vote_average=6.0, vote_count=50, popularity=5.0),
            make_movie("102", "High", vote_average=9.0, vote_count=5000, popularity=90.0),
        ]
    )

    assert ranked[0]["tmdb_source_movie_id"] == "102"
    assert ranked[0]["score"] > ranked[1]["score"]


def test_rank_seed_recommendation_candidates_keeps_missing_signals_explicit():
    service = LookupService(DummySession(), DummyTmdb())
    ranked = service.rank_seed_recommendation_candidates([make_movie("101", "Bare")])
    result = ranked[0]

    assert "critic_consensus" in result["missing_signals"]
    assert "audience_reception" in result["missing_signals"]
    assert "popularity" in result["missing_signals"]
    assert result["freshness"]["critic_consensus"] == "MISSING"


def test_rank_seed_recommendation_candidates_tie_breaks_by_provider_position_then_tmdb_id():
    service = LookupService(DummySession(), DummyTmdb())
    tied_movies = [
        make_movie("200", "A"),
        make_movie("100", "B"),
    ]
    ranked = service.rank_seed_recommendation_candidates(tied_movies)
    assert [item["tmdb_source_movie_id"] for item in ranked] == ["200", "100"]

    reversed_ranked = service.rank_seed_recommendation_candidates(list(reversed(tied_movies)))
    assert [item["tmdb_source_movie_id"] for item in reversed_ranked] == ["100", "200"]


def test_rank_seed_recommendation_candidates_caps_results_at_20():
    service = LookupService(DummySession(), DummyTmdb())
    ranked = service.rank_seed_recommendation_candidates([make_movie(str(i), f"Movie {i}") for i in range(25)])

    assert len(ranked) == 20


def test_rank_seed_recommendation_candidates_repeated_calls_are_identical():
    service = LookupService(DummySession(), DummyTmdb())
    movies = [
        make_movie("101", "Heat", vote_average=8.0, vote_count=1000, popularity=50.0),
        make_movie("102", "Collateral", vote_average=7.0, vote_count=500, popularity=40.0),
    ]

    first = service.rank_seed_recommendation_candidates(movies)
    second = service.rank_seed_recommendation_candidates(movies)

    assert first == second


def test_rank_seed_recommendation_candidates_returns_empty_for_empty_input():
    service = LookupService(DummySession(), DummyTmdb())
    assert service.rank_seed_recommendation_candidates([]) == []
