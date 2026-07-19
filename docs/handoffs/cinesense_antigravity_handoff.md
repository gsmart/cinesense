# cineSense Antigravity Handoff

Date: July 19, 2026

## 1. Project goal

`cineSense` is aiming toward a transparent, region-aware, eventually personalized movie recommendation engine. The current repository already supports lookup, recommendations, and discovery, but ranking authority stays deterministic and backend-owned, with every important score input carrying provenance and freshness instead of opaque LLM output.

## 2. Architecture

- Next.js frontend in `apps/web`
- FastAPI backend in `services/api`
- PostgreSQL for canonical movie storage, aliases, external IDs, observations, and freshness-aware reuse
- Docker Compose in `compose.yaml` for local `db`, `api`, and `web`
- TMDB is the live provider boundary for application requests
- Wikidata is used only for offline identity enrichment in the regional evidence pipeline
- Ranking is deterministic and backend-owned
- LLM use is optional and bounded to natural-language discovery interpretation; it is not ranking authority
- IMDb scraping and Rotten Tomatoes scraping are prohibited

## 3. Current repository state

- Inspected branch on July 19, 2026: `main`
- Exact inspected HEAD on July 19, 2026: `dc3108b9897a849ced00feea2403523c50638cf7`
- Working tree state on July 19, 2026: clean according to `git status --short`
- `planning.md` still records an older inspected HEAD (`7ccb601dd0a738ca10b9bddeae47f3cb1ae520f9`); trust Git state over that stale metadata

Latest relevant commits:

- `dc3108b` Add offline regional human judgment workflow
- `7ccb601` Add project decisions plans and Phase 2D documentation
- `1e30565` Add multilingual shadow ranking evaluation
- `da16025` Synchronize implementation documentation
- `5f6b8e0` Add cine-score v2 shadow scoring prototype

Latest verified checks rerun on July 19, 2026:

- backend regression: `196 passed, 1 deselected`
- frontend production build: passed
- frontend build warnings: existing Next.js `@next/next/no-img-element` warnings in `apps/web/components/discovery-form.tsx` and `apps/web/components/movie-card.tsx`

## 4. Implemented product stages

- Phase 1A exact lookup: production application behavior. Exact movie lookup, cache/freshness reuse, persistence, disambiguation, and `cine-score-v1` are implemented end to end.
- Phase 1B seed recommendations: production application behavior. Recommendation retrieval, persistence reuse, deterministic ordering, and UI rendering are implemented.
- Structured discovery: production application behavior. Provider-neutral request validation, bounded TMDB discovery mapping, deterministic ranking, and `/discover` UI exist.
- Natural-language discovery boundary: provisional application behavior. Optional backend LLM interpretation exists, but ranking and validation remain deterministic and backend-owned.
- Ranking-version foundation: production foundation. Shared ranking input and dispatcher are committed, with production pinned to `cine-score-v1`.
- Regional evidence sampling: provisional offline-only workflow. TMDB sample building plus Wikidata enrichment run through scripts and artifacts, not product APIs.
- Wikidata enrichment and transport handling: provisional offline-only workflow. Implemented in the evidence pipeline, bounded and manifest-backed.
- Regional evidence validation and review gate: provisional offline-only workflow. Validation outputs and manual review sample generation exist, but approval remains manual.
- Cohort baseline builder: provisional offline-only workflow. Language and fallback cohort baselines are built from validated artifacts and remain artifact-backed.
- `cine-score-v2` shadow scorer: shadow-only offline workflow. Implemented in code and scripts, explicitly not active in user-facing ordering.
- Multilingual shadow diagnostic evaluation: completed diagnostic stage. Offline evaluation artifacts and deterministic diagnostics are implemented.
- Multilingual human judgment workflow: implemented offline workflow, still awaiting real human input. Blinded case generation, reviewed snapshot import, and bounded weight evaluation are committed, but there is no repository evidence that real product-owner judgments have been supplied.

## 5. Current ranking state

- `cine-score-v1` is still the active production ranking.
- `cine-score-v2-shadow-1` is offline and shadow-only.
- No `v2` weight configuration is approved for production use.
- No production ordering switch is permitted from current repository evidence.
- Synthetic smoke judgments in tests are not real evaluation evidence.

## 6. Phase 2R.3A state

- Multilingual diagnostics are implemented in `services/api/app/regional_shadow_evaluation.py` and `services/api/scripts/evaluate_regional_shadow_ranking.py`.
- Repository evidence supports a deterministic 150-film host diagnostic fixture across Marathi, Malayalam, and Tamil through the regional pipeline tests; treat that as fixture-backed diagnostic coverage, not product proof.
- No human judgments existed during this diagnostic stage.
- Rank movement, overlap, or correlation diagnostics do not by themselves prove improvement.

## 7. Phase 2R.3B state

Committed code in `services/api/app/regional_human_judgment.py` and the matching CLI scripts now provides:

- deterministic blinded judgment-case generation
- strict CSV validation
- immutable-column protection
- formula-injection safeguards
- reviewed snapshot generation
- bounded weight-grid evaluation
- overfitting safeguards through an explicit small candidate grid and manual recommendation output
- no automatic activation

State this plainly:

- the reviewer inputs exercised in committed tests are synthetic smoke data
- `popularity_split` and `quality_plus` are workflow-verification outcomes only
- they must not be treated as product recommendations
- no real product-owner judgment set is evidenced in the repository

## 8. Current blockers and unresolved gates

- real human review is still pending
- evidence approval remains unresolved
- reviewed evidence snapshot approval remains unresolved even though reviewed-snapshot generation is implemented
- no production activation gate has passed
- `/tmp` artifacts produced by offline scripts must not be assumed to exist
- National Film Awards input exists only as an optional manual fixture path in the offline evidence pipeline; do not describe it as an integrated live source unless new repository evidence is added

## 9. Immediate next legitimate action

The next legitimate action is product-owner human review using the generated blinded CSV, not automatic weight tuning.

Recommended sequence:

1. Regenerate or locate the current deterministic judgment cases from committed evaluation artifacts.
2. Have a human reviewer complete only the reviewer-editable fields in the CSV.
3. Validate and import the completed CSV.
4. Generate the immutable reviewed snapshot.
5. Run the bounded `cine-score-v1` versus `cine-score-v2` weight comparison.
6. Inspect overall and per-language results.
7. Decide manually whether more review is required before any further ranking decision.

Additional engineering should be limited to defects or usability issues discovered while executing that review workflow.

## 10. Later engineering stage

Only after real human judgments exist and show a stable result should the next engineering stage be considered: controlled runtime shadow integration.

That future stage must:

- keep `cine-score-v1` active
- score real recommendation or discovery candidates in shadow only
- persist or log only approved bounded diagnostics
- compare `v1` and `v2` in real query contexts
- define explicit activation and rollback gates
- remain disabled by default

This is not the immediate task.

## 11. Important commands

Git state inspection:

- `cd /Users/ganeshsawant/Documents/work/cineSense/cinesense && git branch --show-current`
- `cd /Users/ganeshsawant/Documents/work/cineSense/cinesense && git rev-parse HEAD`
- `cd /Users/ganeshsawant/Documents/work/cineSense/cinesense && git status --short`
- `cd /Users/ganeshsawant/Documents/work/cineSense/cinesense && git log -12 --oneline`

Backend focused tests:

- `cd /Users/ganeshsawant/Documents/work/cineSense/cinesense/services/api && ../../.venv/bin/pytest tests/test_ranking_foundation.py tests/test_cine_score_v2.py tests/test_regional_shadow_scoring.py tests/test_regional_shadow_evaluation.py tests/test_regional_human_judgment.py -q`

Full backend regression:

- `cd /Users/ganeshsawant/Documents/work/cineSense/cinesense/services/api && ../../.venv/bin/pytest -q`

Frontend build:

- `cd /Users/ganeshsawant/Documents/work/cineSense/cinesense/apps/web && npm run build`

Build judgment cases:

- `cd /Users/ganeshsawant/Documents/work/cineSense/cinesense/services/api && ../../.venv/bin/python scripts/build_regional_judgment_cases.py --evaluation-dir /tmp/cinesense-regional-evaluation/<run-id>`

Validate and import reviewed judgments:

- `cd /Users/ganeshsawant/Documents/work/cineSense/cinesense/services/api && ../../.venv/bin/python scripts/import_regional_judgments.py --judgment-dir /tmp/cinesense-regional-judgment-cases/<run-id> --reviewed-csv /absolute/path/to/reviewed.csv`

Evaluate weight configurations:

- `cd /Users/ganeshsawant/Documents/work/cineSense/cinesense/services/api && ../../.venv/bin/python scripts/evaluate_regional_weight_configs.py --judgment-dir /tmp/cinesense-regional-judgment-cases/<run-id> --reviewed-dir /tmp/cinesense-regional-reviewed-judgments/<run-id> --shadow-dir /tmp/cinesense-regional-shadow/<run-id> --evaluation-dir /tmp/cinesense-regional-evaluation/<run-id>`

Docker smoke verification:

- `cd /Users/ganeshsawant/Documents/work/cineSense/cinesense && docker compose up --build`

Offline pipeline entry points that feed the review workflow:

- `cd /Users/ganeshsawant/Documents/work/cineSense/cinesense/services/api && ../../.venv/bin/python scripts/build_regional_evidence_sample.py --help`
- `cd /Users/ganeshsawant/Documents/work/cineSense/cinesense/services/api && ../../.venv/bin/python scripts/validate_regional_evidence_sample.py --help`
- `cd /Users/ganeshsawant/Documents/work/cineSense/cinesense/services/api && ../../.venv/bin/python scripts/build_regional_cohort_baselines.py --help`
- `cd /Users/ganeshsawant/Documents/work/cineSense/cinesense/services/api && ../../.venv/bin/python scripts/run_regional_shadow_scoring.py --help`
- `cd /Users/ganeshsawant/Documents/work/cineSense/cinesense/services/api && ../../.venv/bin/python scripts/evaluate_regional_shadow_ranking.py --help`

## 12. Agent operating rules

- Inspect the repository and Git state before acting.
- Prompts and prior chat summaries are not proof of implementation.
- Do not fabricate tests, artifacts, approval states, or review decisions.
- Do not treat synthetic judgments as product evidence.
- Do not activate `cine-score-v2`.
- Do not modify `cine-score-v1` without a new approved ranking version.
- Do not use `git add .`.
- Do not commit or push unless explicitly requested.
- Keep changes small and independently testable.
- Run focused and full regressions when you touch non-trivial backend logic.
- Update the authoritative docs when architecture, phase status, ranking state, verification state, source boundaries, or security boundaries change.

## 13. Recommended kickoff prompt

```text
Inspect the cineSense repository and current Git state first. Read docs/handoffs/cinesense_antigravity_handoff.md plus README.md, planning.md, designing.md, verification.md, ranking.md, tools.md, data_sources.md, agentic.md, security_licensing.md, code_review.md, docs/decisions/, docs/plans/, and the Phase 2R implementation records. Verify that Phase 2R.3B is actually committed in code at the current HEAD. Then verify whether any real human review file exists in the repository or only synthetic/test inputs exist. Do not activate cine-score-v2 or treat synthetic judgments as product evidence.
```
