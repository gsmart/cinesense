from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class FreshnessState(StrEnum):
    FRESH = "FRESH"
    STALE_USABLE = "STALE_USABLE"
    EXPIRED = "EXPIRED"
    MISSING = "MISSING"
    REFRESH_FAILED = "REFRESH_FAILED"


@dataclass(slots=True)
class FreshnessWindow:
    fresh_until: datetime | None
    stale_until: datetime | None
    fetch_status: str | None = None


def evaluate_freshness(window: FreshnessWindow, now: datetime | None = None) -> FreshnessState:
    current = now or datetime.now(UTC)
    if not window.fresh_until or not window.stale_until:
        return FreshnessState.MISSING
    if window.fetch_status == "REFRESH_FAILED":
        return FreshnessState.REFRESH_FAILED
    if current <= window.fresh_until:
        return FreshnessState.FRESH
    if current <= window.stale_until:
        return FreshnessState.STALE_USABLE
    return FreshnessState.EXPIRED

