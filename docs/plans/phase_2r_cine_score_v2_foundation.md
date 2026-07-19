# cine-score-v2 Foundation Plan

Status: completed on July 19, 2026
Implementation date: July 19, 2026

## Summary

Build the smallest versioned-ranking foundation first, without changing `cine-score-v1` behavior or public production ordering.

Historical note:
- this plan covers the foundation seam only
- later committed work extended that seam with offline regional evidence, cohort baselines, and `cine-score-v2-shadow-1`
- production ordering still remains on `cine-score-v1`

Current state confirmed from the repo on July 19, 2026:
- `cine-score-v1` is a composite score, not a pure quality score.
- It mixes relevance (`query_match` / seed position), audience score, popularity, evidence count, and coverage into one additive total.
- Exact lookup, seed recommendations, structured discovery, and natural-language discovery all ultimately depend on `compute_cine_score_v1`.
- Ranking tie-breaks are outside the scorer in service code: total desc, then `provider_position`, then TMDB source ID.
- Natural-language discovery does not have its own ranking; it only interprets text into `DiscoveryRequest` and reuses structured discovery.

Chosen product defaults:
- `v2` goal: better non-personalized discovery ordering first.
- comparison exposure: offline only at first.
- version control: server-side config only at first.

## Implementation Changes

### 1. Introduce one provider-neutral ranking input contract
Add one typed backend-only input object for scoring, used by all ranking call sites before any scorer runs.

It should include only fields already used or already available from current persistence:
- `normalized_query`
- `canonical_title`
- `release_year`
- `requested_year`
- `seed_relevance`
- `vote_average`
- `vote_count`
- `popularity`
- `missing_signals`
- `freshness` summary per signal when available
- stable identifiers needed for deterministic comparison only: TMDB source ID, provider position

Do not include raw provider payloads.
Do not coerce missing values to zero inside the contract.

Fields available now:
- title/year/query inputs
- audience observation and evidence count
- popularity observation
- missing-signal list
- observation freshness states
- seed/provider position context

Fields not available now and therefore out of first implementation:
- reliable genres/language/era cohort baselines for scoring
- critic consensus inputs
- persisted cohort stats or baseline versions
- broader-catalog calibration data

### 2. Add the smallest versioned scorer boundary
Keep `compute_cine_score_v1` intact.

Add:
- a small `build_ranking_input(...)` helper to normalize service-layer scorer inputs into the shared contract
- a small dispatcher function, not a registry-heavy framework:
  - `compute_ranking(input, requested_version, config) -> RankingComputation`
  - internally routes by explicit version string
  - calls `compute_cine_score_v1` unchanged for v1
  - later can call `compute_cine_score_v2`

Do not add protocol/registry/config objects unless the second scorer actually needs them.
The dispatcher is the seam that prevents version conditionals from spreading through services.

### 3. Define explicit ranking result and fallback semantics
Introduce one internal result shape for all scorer executions:

- `requested_ranking_version`
- `applied_ranking_version`
- `fallback_used`
- `fallback_reason`
- `status`
- `total`
- `components`
- `missing_signals`

Rules:
- missing evidence is normal and stays in `missing_signals`
- unsupported or unavailable v2 prerequisites may fall back to v1 with an explicit safe reason
- invalid configured version is an implementation error and should fail loudly in development/tests
- unexpected scorer exceptions should fail tests, not be silently swallowed
- fallback is explicit in internal results from day one

Initial server config:
- `active_ranking_version = cine-score-v1`
- `shadow_ranking_version = disabled`
- `fallback_ranking_version = cine-score-v1`

Future experimental config:
- `active = v1`
- `shadow = v2`
- `fallback = v1`

Use backend settings/constants only for this phase. No DB config, no admin UI, no request parameter.

### 4. Centralize ranking orchestration in service code
Replace direct `compute_cine_score_v1` calls in service paths with one shared ranking entrypoint.

Apply this to:
- exact lookup scoring
- seed recommendation ranking
- structured discovery ranking
- natural-language discovery indirectly through structured discovery

Keep current output fields stable for existing APIs:
- `score`
- `score_version`
- `score_components`
- `missing_signals`

For the first phase, map these from the internal ranking result exactly as today so clients stay unchanged.

Do not expose requested/applied/fallback metadata in public production responses yet.
Keep side-by-side comparison internal and offline only.

### 5. Freeze v1 explicitly
Document and test `cine-score-v1` as frozen across:
- formula
- component names
- component maximums
- rounding
- missing-data behavior
- version string
- total calculation
- lookup/recommendation/discovery tie-break behavior

Current undocumented or weakly protected areas that should be locked by tests:
- exact numeric outputs for representative cases, not just “greater than zero”
- coverage behavior staying tied to present component count
- popularity scaling staying `popularity / 100 * 10`
- evidence confidence staying `log10(vote_count + 1) / 4 * 20`
- exact seed-relevance decay by provider position
- service-layer tie-break keys remaining unchanged

### 6. Add offline shadow-comparison foundation only
Add one internal comparison path and one offline audit/script path.

Comparison output should capture:
- v1 total/components
- v2 total/components when available
- score delta
- ordering delta within an evaluated set
- missing inputs
- warnings
- scorer versions
- deterministic identifiers: TMDB source ID, provider position, case ID

First implementation scope:
- comparison available from internal audit utilities and offline scripts only
- no persistence
- no public endpoint
- no production response expansion

### 7. Defer cohort-aware scoring until data is real
Conclusion from current repo state:
- the repository does not yet have enough data for meaningful cohort-calibrated v2 scoring
- current storage is title-centric and candidate-centric, not catalog-wide enough for reliable language/era/genre baselines
- critic consensus is absent
- genre data is validated at request level, but not established as a scorer-ready persisted baseline source
- sparse provider coverage would make small cohorts easy to overfit and easy to bias toward low-volume films

Smallest safe next phase after this foundation:
- implement the version-selection, shared input, fallback, and offline comparison scaffolding first
- keep `v2` disabled until a real formula and evaluation fixtures are approved
- then add a genuine `v2` scorer only when its required inputs and regression cases are specified

## Public/API Contract Notes

Public responses remain backward-compatible in the first implementation phase:
- keep `score` as the authoritative displayed total
- keep `score_version`
- keep `score_components`
- keep `missing_signals`

No silent semantic change:
- `score_version` must continue to describe the applied scorer
- existing fields must remain authoritative for ordering
- experimental comparison data stays internal/offline for now

Internal additions only:
- shared ranking input type
- shared ranking computation result
- shared dispatcher
- optional comparison result type for offline audits

## Test Plan

Add focused checks that lock current behavior and the new foundation:

1. v1 freeze tests
- exact expected totals/components for selected lookup, recommendation, and discovery fixtures
- exact audit fixture expectations for A-G cases
- exact tie-break order for equal totals

2. dispatcher tests
- requested `cine-score-v1` returns applied `cine-score-v1`
- unknown version fails loudly
- disabled/unavailable shadow version does not affect active ordering

3. fallback tests
- explicit fallback metadata when a requested experimental scorer is unavailable
- no silent fallback on invalid configuration
- missing signals remain missing, not converted to zeros

4. service integration tests
- exact lookup payload remains unchanged with active v1
- recommendation payload remains unchanged with active v1
- discovery payload remains unchanged with active v1
- natural-language discovery still preserves backend order and same score fields

5. offline comparison checks
- comparison script can compute stable v1 baseline
- when v2 is absent or disabled, comparison output is controlled and explicit
- no DB writes, provider calls, or LLM calls for synthetic audit fixtures

Baseline commands already confirmed on July 19, 2026:
- `cd /Users/ganeshsawant/Documents/work/cineSense/cinesense/services/api`
- `../../.venv/bin/pytest tests/test_regional_ranking_audit.py tests/test_core.py tests/test_recommendation_ranking.py tests/test_discovery_pipeline.py -v`
- result: `30 passed`
- `../../.venv/bin/python scripts/audit_regional_ranking.py`
- result: fixture-only audit output showing v1 currently favors high popularity and high evidence over lower-volume regional/older candidates

## Assumptions

- `cine-score-v1` remains the only production ranking until a separate approval explicitly promotes v2.
- First implementation phase is foundation-only, not a real v2 formula rollout.
- No database schema change is required for the first foundation phase.
- No public API expansion is required for the first foundation phase.
- No new provider, scraping path, critic source, auth layer, or experiment platform is introduced.
