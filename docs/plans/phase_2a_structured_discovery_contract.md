# Phase 2A Structured Discovery Contract

## Goal

Define the backend-owned, provider-neutral structured request contract for movie discovery before any provider integration, persistence, API, UI, or LLM wiring. The contract must serve both manual filters and a future LLM interpreter through one validation path and one normalized JSON schema.

## In Scope

- `movie` media type only
- canonical genre slugs
- original language
- region
- release-year range
- runtime range
- minimum evidence count
- `availability_required`
- page and page size
- normalization
- cross-field validation

## Out Of Scope

- TMDB Discover calls
- persistence
- ranking execution
- API endpoint
- frontend
- LLM integration
- subjective mood or pace interpretation

## Provider-Neutral Boundaries

- no TMDB genre IDs in the public contract
- no provider-specific query parameters
- no ranking weights
- no free-text bypass
- future LLM output must validate through the same schema

## Validation Decisions

- Canonical genre slugs use a neutral TMDB-aligned movie set, exposed only as slugs:
  - `action`
  - `adventure`
  - `animation`
  - `comedy`
  - `crime`
  - `documentary`
  - `drama`
  - `family`
  - `fantasy`
  - `history`
  - `horror`
  - `music`
  - `mystery`
  - `romance`
  - `science-fiction`
  - `thriller`
  - `tv-movie`
  - `war`
  - `western`
- `original_language` uses ISO-shaped lowercase language codes with shape validation only.
- `region` uses ISO-shaped uppercase region codes with shape validation only.
- Release-year bounds are `1888..current year + 1` at validation time.
- Runtime bounds are `1..400` minutes.
- Page size maximum is `20`.
- `availability_required=true` requires `region`.
- Unrestricted discovery requests are rejected when no meaningful narrowing filters are present after normalization.
- Meaningful narrowing filters are:
  - one or more supported genres
  - `original_language`
  - release-year range with at least one bound
  - runtime range with at least one bound
  - `minimum_evidence_count > 0`
  - `availability_required=true` together with `region`
- `region` alone is not a meaningful narrowing filter.
- `minimum_evidence_count=0` is not a meaningful narrowing filter.
- Normalization is deterministic:
  - trim surrounding whitespace
  - lowercase genre slugs and language
  - uppercase region
  - deduplicate and sort genres
  - preserve inclusive min/max semantics for ranges

## Acceptance Criteria

- valid request succeeds
- normalization is deterministic
- invalid ranges fail
- unsupported genres fail
- malformed codes fail
- unrestricted requests fail
- serialized JSON schema is stable for future structured LLM output

## Verification Plan

- focused schema tests only
- no Docker, provider, or frontend checks for Phase 2A
- How to check as a user: this is an internal contract only and has no public API or UI yet

## Phase Boundaries

- Phase 2A: structured contract
- Phase 2B: TMDB Discover adapter
- Phase 2C: persistence and deterministic ranking
- Phase 2D: API and manual filter UI
- Phase 2E: LLM interpreter
- Phase 2F: clarification, validation, and editable fallback
- Phase 2G: regional availability refinement

## Open Questions And Locked Decisions

- TMDB Discover is the proposed Phase 2B candidate provider.
- LLM remains an interpreter only.
- Backend code remains authoritative for validation and ranking.

## Recommended Next Implementation Prompt Seed

Implement the approved Phase 2A schema and normalization layer only, with focused schema tests and no provider, API, UI, persistence, ranking-execution, or LLM-integration work.
