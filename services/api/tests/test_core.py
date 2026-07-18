from datetime import UTC, datetime, timedelta

import httpx

from app.core.freshness import FreshnessState, FreshnessWindow, evaluate_freshness
from app.core.normalization import normalize_region, normalize_title
from app.core.scoring import compute_cine_score_v1
from app.services import LookupService


def test_normalize_title_strips_case_and_punctuation() -> None:
    assert normalize_title("  WALL-E! ") == "wall e"


def test_normalize_region_uppercases() -> None:
    assert normalize_region(" us ") == "US"


def test_freshness_transitions() -> None:
    now = datetime(2026, 7, 18, tzinfo=UTC)
    assert (
        evaluate_freshness(
            FreshnessWindow(
                fresh_until=now + timedelta(days=1),
                stale_until=now + timedelta(days=2),
            ),
            now,
        )
        == FreshnessState.FRESH
    )
    assert (
        evaluate_freshness(
            FreshnessWindow(
                fresh_until=now - timedelta(hours=1),
                stale_until=now + timedelta(days=2),
            ),
            now,
        )
        == FreshnessState.STALE_USABLE
    )
    assert (
        evaluate_freshness(
            FreshnessWindow(
                fresh_until=now - timedelta(days=3),
                stale_until=now - timedelta(days=1),
            ),
            now,
        )
        == FreshnessState.EXPIRED
    )


def test_cine_score_v1_penalizes_missing_signals_but_stays_deterministic() -> None:
    score = compute_cine_score_v1(
        normalized_query="the dark knight",
        canonical_title="the dark knight",
        release_year=2008,
        requested_year=2008,
        vote_average=8.5,
        vote_count=32000,
        popularity=85.0,
        missing_signals=["critic_consensus"],
    )
    assert score["version"] == "cine-score-v1"
    assert score["components"]["critic_consensus"] is None
    assert score["total"] > 0


class _DummySession:
    def scalars(self, _stmt):
        class _Result:
            def unique(self):
                return []

        return _Result()


class _FailingTmdb:
    enabled = True

    async def search_titles(self, *_args, **_kwargs):
        raise httpx.ConnectError("boom")


def test_lookup_surfaces_tmdb_connect_errors_as_runtime_error() -> None:
    service = LookupService(_DummySession(), _FailingTmdb())
    try:
        import asyncio

        asyncio.run(service.lookup(title="The Dark Knight", year=2008, region=None, media_type="movie"))
    except RuntimeError as exc:
        assert str(exc) == "TMDB request failed"
    else:
        raise AssertionError("expected RuntimeError")
