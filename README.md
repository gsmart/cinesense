# cineSense

Transparent, region-aware movie discovery with deterministic backend ranking, local persistence, and explicit provenance for every score input.

## Current Status

As of July 19, 2026, `cineSense` is past Phase 1. The committed repository implements:

- exact movie lookup with disambiguation
- seed-based recommendations
- structured discovery API and `/discover` UI
- natural-language discovery interpretation behind an optional backend LLM boundary
- versioned ranking dispatch with production pinned to `cine-score-v1`
- offline regional evidence sampling, validation, cohort baseline building, and `cine-score-v2` shadow scoring prototypes

Production ranking version:
- `cine-score-v1`

Current non-production shadow version:
- `cine-score-v2-shadow-1`

Experimental or provisional capabilities:
- natural-language discovery requires explicit `CINESENSE_LLM_*` configuration and can return controlled interpreter-unavailable responses
- regional evidence, review gates, cohort baselines, and shadow scoring run offline through scripts and JSON/JSONL artifacts; they are not production API features
- blinded regional human-judgment case generation, review import, and bounded `cine-score-v2` weight evaluation run offline through scripts and local artifacts only
- `cine-score-v2` is not active for user-facing ordering

## Runtime Architecture

- `apps/web`: Next.js 15 app for lookup, recommendations, structured discovery, and natural-language discovery UI
- `services/api`: FastAPI service for lookup, recommendations, structured discovery, natural-language interpretation, ranking, and offline regional analysis scripts
- PostgreSQL: canonical movie storage, aliases, external IDs, observations, and freshness-aware reuse
- `compose.yaml`: local orchestration for `db`, `api`, and `web`

## Local Setup

1. Copy `.env.example` to `.env`.
2. Set `TMDB_API_READ_ACCESS_TOKEN` for lookup, recommendations, and discovery.
3. Set `CINESENSE_LLM_*` only if you want natural-language discovery enabled locally.
4. Run `./scripts/start-phase-1a.sh` from the repo root.
5. Open `http://localhost:3000` or `http://localhost:3000/discover`.

## Core Verification

- `cd services/api && ../../.venv/bin/pytest -q`
- `cd apps/web && npm run build`
- `cd services/api && ../../.venv/bin/python scripts/audit_regional_ranking.py`
- `cd services/api && ../../.venv/bin/python scripts/build_regional_evidence_sample.py --help`
- `cd services/api && ../../.venv/bin/python scripts/build_regional_cohort_baselines.py --help`
- `cd services/api && ../../.venv/bin/python scripts/run_regional_shadow_scoring.py --help`
- `cd services/api && ../../.venv/bin/python scripts/build_regional_judgment_cases.py --help`
- `cd services/api && ../../.venv/bin/python scripts/import_regional_judgments.py --help`
- `cd services/api && ../../.venv/bin/python scripts/evaluate_regional_weight_configs.py --help`

## Documentation Map

- `planning.md`: current phase ledger, milestone status, risks, blockers, open decisions
- `designing.md`: implemented runtime boundaries, persistence model, discovery flow, and offline evidence/shadow pipeline
- `verification.md`: current automated checks, user verification steps, and offline artifact checks
- `agentic.md`: LLM interpreter boundary and deterministic backend ownership
- `tools.md`: TMDB, Wikidata, interpreter, and offline script/tool contracts
- `data_sources.md`: approved, provisional, and prohibited sources
- `ranking.md`: `cine-score-v1`, versioned ranking dispatch, and `cine-score-v2` shadow prototype status
- `ranking.md`: also documents the offline human-judgment and bounded weight-evaluation workflow
- `security_licensing.md`: secret handling, scraping prohibitions, review-file safety, and launch gates
- `code_review.md`: review checklist for the implemented platform
- `docs/plans/`: phase plans and accepted scope boundaries
- `docs/phase_*.md`: concise completion and handoff notes
- `docs/decisions/`: durable architecture decisions

## Next Milestone

The next milestone is not another production feature. It is proving whether the offline regional evidence and `cine-score-v2` shadow pipeline is good enough to justify a future activation plan. Current uncommitted work on regional shadow evaluation is not part of the last committed milestone.
