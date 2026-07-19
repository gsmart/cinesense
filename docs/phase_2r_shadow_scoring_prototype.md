# Phase 2R Shadow Scoring Prototype

Date: July 19, 2026
Authoritative committed milestone: `5f6b8e0 Add cine-score v2 shadow scoring prototype`

## What Works

- offline `cine-score-v2-shadow-1` scoring exists in `services/api/app/cine_score_v2.py`
- offline regional shadow scoring orchestration exists in `services/api/app/regional_shadow_scoring.py`
- `services/api/scripts/run_regional_shadow_scoring.py` writes shadow scores, rankings, comparisons, summaries, and manifests
- cohort baseline hashes and fallback paths are recorded in outputs
- production lookup, recommendations, and discovery remain on `cine-score-v1`

## Verification

- backend regression suite: `188 passed, 1 deselected`
- frontend production build: passed
- focused shadow-scoring tests exist in:
  - `services/api/tests/test_cine_score_v2.py`
  - `services/api/tests/test_regional_shadow_scoring.py`

## Boundaries

- this is an offline prototype, not a production scorer
- no public API switches users to `cine-score-v2`
- activation eligibility remains false in the committed shadow orchestration
- regional evidence review and cohort quality remain gating inputs, not solved problems

## Recommended Next Prompt Seed

Evaluate whether the current regional evidence and cohort baseline artifacts are strong enough to keep investing in `cine-score-v2`; do not activate it in production and do not bypass the offline gate with ad hoc API changes.
