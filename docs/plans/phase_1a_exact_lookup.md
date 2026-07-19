# Phase 1A Exact Lookup

## Goal

Prove the ingestion, cache, freshness, provenance, persistence, and scoring pipeline for one exact movie lookup.

## In Scope

- exact-title input
- canonical resolution
- approved provider fetch on miss or stale need
- persistence of canonical movie and observations
- `cine-score-v1`
- one movie detail response with source and freshness

## Out Of Scope

- recommendation quality claims
- collaborative filtering
- free-text discovery ranking
- unsupported providers or scraping

## Planned Execution Order

1. Create the minimal service skeleton for web, API, and PostgreSQL.
2. Implement title normalization and local lookup.
3. Implement TMDB-backed candidate resolution adapter.
4. Implement persistence for canonical movies, aliases, external IDs, and observations.
5. Implement freshness-state evaluation and bounded refresh policy.
6. Implement `cine-score-v1` calculation and response payload.
7. Verify warm-cache and stale-usable behaviour.

## Acceptance Focus

- `The Dark Knight` resolves exactly to the 2008 movie
- `Crash` triggers disambiguation
- repeated fresh lookup reuses local data
- stale and missing states are explicit

## Open Questions

### 1. Disambiguation threshold

- Question: when should the API stop auto-resolving and ask the user?
- Available options: strict title/year match only, confidence threshold, provider ranking only
- Recommended option: confidence threshold informed by title, year, and media type
- Reason: avoids false positives without making exact lookup unusably rigid
- Impact on Phase 1: high
- User approval required: yes

