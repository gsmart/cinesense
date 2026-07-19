# Phase 1B Seed Recommendations

Status: complete on July 18, 2026.

## Goal

Use one exact resolved movie as a seed and return up to 20 deterministic recommendations.

## In Scope

- seed resolution reuse from Phase 1A
- bounded candidate discovery from approved provider
- deduplication by canonical and external IDs
- enrichment from local/provider data
- deterministic ranking output with freshness and provenance

## Out Of Scope

- unconstrained search
- hidden availability boosts
- LLM-authored rankings

## Planned Execution Order

1. Reuse Phase 1A canonical resolution.
2. Add one approved discovery candidate source.
3. Deduplicate and enrich candidates.
4. Apply versioned ranking.
5. Return paged results capped at 20.

## Outcome

Implemented and verified:
- seed recommendations work through API and UI
- recommendation responses are capped at 20
- ranking is deterministic using `cine-score-v1`
- exact lookup, caching, scoring, and disambiguation from Phase 1A continue to work
- normal backend suite: 53 passed, 1 integration test deselected
- Docker PostgreSQL integration: 1 passed
- frontend production build: passed
- Compose validation: passed
- live API and UI verification: passed

No known Phase 1 blocker remains. Phase 2 scope must be planned and approved before implementation.

## Open Questions

### 1. Candidate-set source

- Question: which provider should own bounded recommendation candidates?
- Available options: TMDB only, licensed feed only, hybrid merge
- Recommended option: TMDB only for the first pass
- Reason: smallest implementation surface and easiest provenance story
- Impact on Phase 1: high for delivery pace
- User approval required: yes
