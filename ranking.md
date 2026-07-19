# Ranking

## Production Ranking Boundary

Ranking is deterministic, backend-owned, and versioned.

Current production ranking version:
- `cine-score-v1`

Current shadow-only version:
- `cine-score-v2-shadow-1`

The LLM does not calculate ranking.

## `cine-score-v1`

`cine-score-v1` remains the only applied production scorer for:

- exact lookup result cards
- seed recommendations
- structured discovery
- natural-language discovery results

Committed repository evidence shows `cine-score-v1` is now routed through a shared ranking input and dispatcher, but its public behavior remains the production default.

Principles:

- missing signals remain missing
- deterministic ordering is preserved
- availability is not a hidden quality boost
- formula changes require a new version plus regression checks

## Versioned Ranking Foundation

The ranking foundation added at Phase 2R introduces:

- shared ranking input construction
- one internal dispatcher
- explicit requested/applied/fallback semantics internally
- frozen `cine-score-v1` expectations

Public API behavior stays stable:

- `score`
- `score_version`
- `score_components`
- `missing_signals`

No committed production endpoint exposes fallback metadata yet.

## `cine-score-v2` Shadow Prototype

The committed repository now includes an offline shadow scorer:

- score version: `cine-score-v2-shadow-1`
- input basis: regional cohort baselines and cohort-specific signal percentiles
- active components:
  - quality
  - vote reach
  - popularity reach
  - confidence

Current status:

- offline only
- driven by artifact files, not application requests
- compared against a `cine-score-v1` proxy in generated comparison outputs
- gated by evidence coverage and manual review outcomes
- not eligible for production activation

## Missing-Data And Fallback Rules

- production requests continue to tolerate partial data under `cine-score-v1`
- discovery availability filters fail explicitly when unsupported
- shadow scoring can emit missing components, warnings, and fallback cohort paths
- unsupported or weak-evidence regional cohorts reduce confidence rather than silently fabricating values

## Activation State

- active production scorer: `cine-score-v1`
- shadow scorer in product APIs: disabled
- offline shadow experiment: implemented
- production migration path for `cine-score-v2`: not approved
