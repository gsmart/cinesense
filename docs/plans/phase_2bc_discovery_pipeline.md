# Phase 2B + 2C Discovery Pipeline

## Goal

Use the Phase 2A structured discovery contract as input for a backend-only movie discovery pipeline that:
- maps provider-neutral filters to TMDB Discover privately
- retrieves a bounded candidate set
- persists or reuses canonical movie records and approved observations
- ranks results deterministically with `cine-score-v1`

## In Scope

- Phase 2A `DiscoveryRequest` as the only input contract
- TMDB Discover as the approved candidate provider
- private genre-slug to TMDB genre-ID mapping
- bounded candidate retrieval capped at 20
- canonical persistence and observation reuse by TMDB external ID
- deterministic discovery ranking using persisted approved observations
- focused adapter, persistence, ranking, orchestration, and backend regression tests

## Out Of Scope

- public discovery API
- frontend
- LLM interpretation
- streaming availability integration
- additional providers

## Implementation Notes

- `availability_required=true` is treated as a controlled unsupported filter in this slice and does not trigger a TMDB call.
- TMDB genre IDs remain private to the adapter.
- Provider order is preserved before deterministic ranking.
- Persistence reuses existing canonical movies, aliases, external IDs, and observation merge rules where possible.
- Ranking reuses `cine-score-v1` unchanged and feeds discovery/filter match as `1.0` into the existing query-or-seed-match component.

## Acceptance Criteria

- valid Phase 2A discovery requests map to bounded TMDB Discover calls correctly
- malformed provider fields stay `None`
- duplicate TMDB candidates are removed safely
- repeated persistence is idempotent
- repeated ranking and unchanged inputs return identical ordering
- no API, UI, LLM, or availability integration is introduced

## Verification

- focused TMDB discovery-adapter tests
- focused discovery-pipeline tests
- normal backend regression suite

## How To Check As A User

This is an internal backend pipeline only. No public API or UI exists yet for discovery.
