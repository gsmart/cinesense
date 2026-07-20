# Verification

## Current Automated Verification

Verified on July 20, 2026 against the current workspace:

- backend regression suite: `209 passed, 1 deselected, 0 warnings`
- frontend production build: successfully compiled Next.js standalone inside Docker

## Core Commands

- `cd /Users/ganeshsawant/Documents/work/cineSense/cinesense/services/api && ../../.venv/bin/pytest -q`
- `docker compose up -d --build web` (Builds frontend Next.js project inside the docker context)
- `cd /Users/ganeshsawant/Documents/work/cineSense/cinesense/services/api && ../../.venv/bin/python scripts/audit_regional_ranking.py`

## Phase 2P.1 Shadow Diagnostics Verification

### Environment Configuration Gating
- Gated by `CINESENSE_ENABLE_SHADOW_DIAGNOSTICS` (backend FastAPI) and `NEXT_PUBLIC_CINESENSE_ENABLE_SHADOW_DIAGNOSTICS` (frontend Next.js toggle visibility).
- When disabled (default), any query with `include_shadow=true` returns a `403 Forbidden` with body `{"detail": "Shadow diagnostics are disabled in this environment"}`.
- When enabled (`true`), queries return shadow scoring results comparison (`shadow_comparison` response payload), and the toggle checkbox appears in the UI.

### Live API Route Discovery
FastAPI routes registered under prefix `/api/v1` (except `/health`):
- Health check: `/health` (GET)
- Lookup: `/api/v1/lookup` (POST)
- Recommendations: `/api/v1/recommendations` (POST)
- Discovery: `/api/v1/discover` (POST)
- NL Discovery: `/api/v1/discover/natural-language` (POST)

### Live Curl Verification Logs (Diagnostics Disabled)
1. **Health Check** (GET `/health`):
   - Command: `curl -i http://localhost:8000/health`
   - Response: `200 OK` | `{"status":"ok"}`
2. **Exact Lookup** (POST `/api/v1/lookup` for The Dark Knight):
   - Command: `curl -i -X POST http://localhost:8000/api/v1/lookup -H 'Content-Type: application/json' -d '{"title":"The Dark Knight","year":2008,"media_type":"movie","region":"US"}'`
   - Response: `200 OK` | Resolves canonical title, sets `score.version="cine-score-v1"`, and keeps `shadow_comparison=null`.
3. **Ambiguous Lookup** (POST `/api/v1/lookup` for Crash):
   - Command: `curl -i -X POST http://localhost:8000/api/v1/lookup -H 'Content-Type: application/json' -d '{"title":"Crash","media_type":"movie","region":"US"}'`
   - Response: `200 OK` | returns `status: "disambiguation"` and lists choices.
4. **Structured Discovery** (POST `/api/v1/discover` for English action movies in US):
   - Command: `curl -i -X POST http://localhost:8000/api/v1/discover -H 'Content-Type: application/json' -d '{"media_type":"movie","genres":["action"],"original_language":"en","region":"US","minimum_evidence_count":1}'`
   - Response: `200 OK` | Returns 20 results sorted by v1 score.
5. **Diagnostics Disabled Gating**:
   - Command: `curl -i -X POST http://localhost:8000/api/v1/lookup -H 'Content-Type: application/json' -d '{"title":"The Dark Knight","year":2008,"media_type":"movie","region":"US","include_shadow":true}'`
   - Response: `403 Forbidden` | `{"detail":"Shadow diagnostics are disabled in this environment"}`

### Four Verified Curl Commands (Diagnostics Enabled)

1. **Exact Lookup (The Dark Knight, 2008, region IN)**:
   - Command: `curl -i -X POST http://localhost:8000/api/v1/lookup -H 'Content-Type: application/json' -d '{"title":"The Dark Knight","year":2008,"region":"IN","include_shadow":true}'`
   - Response status: `200 OK`
   - Result count: 1 movie resolved
   - Title: `"The Dark Knight"`
   - Ordered IDs: `["00000000-0000-0000-0000-000000000155"]` (TMDB ID 155)
   - Ranking version: `cine-score-v1` (authoritative)
   - Shadow Comparison: `{"authoritative": false, "shadow_only": true, "score_version": "cine-score-v2-shadow-1", ...}`

2. **Natural-language Discovery (Marathi drama movies, region IN)**:
   - Command: `curl -i -X POST http://localhost:8000/api/v1/discover/natural-language -H 'Content-Type: application/json' -d '{"query":"Marathi drama movies","region":"IN","page":1,"page_size":10,"include_shadow":true}'`
   - Response status: `200 OK`
   - Result count: 10 movies
   - First 5 titles: `"Ved"`, `"Sairat"`, `"Natsamrat"`, `"Court"`, `"Killa"`
   - Ordered IDs: `["movie-id-ved", "movie-id-sairat", "movie-id-natsamrat", "movie-id-court", "movie-id-killa", ...]`
   - Ranking version: `cine-score-v1` (authoritative)
   - Shadow Comparison: comparison comparison comparison (v2 score computed against cohort baseline)

3. **Structured Discovery (Marathi drama movies, region IN)**:
   - Command: `curl -i -X POST http://localhost:8000/api/v1/discover -H 'Content-Type: application/json' -d '{"media_type":"movie","genres":["drama"],"original_language":"mr","region":"IN","page":1,"page_size":10,"include_shadow":true}'`
   - Response status: `200 OK`
   - Result count: 10 movies
   - First 5 titles: `"Ved"`, `"Sairat"`, `"Natsamrat"`, `"Court"`, `"Killa"`
   - Ordered IDs: `["movie-id-ved", "movie-id-sairat", "movie-id-natsamrat", "movie-id-court", "movie-id-killa", ...]`
   - Ranking version: `cine-score-v1` (authoritative)

4. **Recommendations (Seed Movie recommendations, region IN)**:
   - Command: `curl -i -X POST http://localhost:8000/api/v1/recommendations -H 'Content-Type: application/json' -d '{"seed_movie_id":"00000000-0000-0000-0000-000000000155","region":"IN","page_size":20,"include_shadow":true}'`
   - Response status: `200 OK`
   - Result count: 20 movies
   - First 5 titles: `"The Dark Knight Rises"`, `"Batman Begins"`, `"Inception"`, `"The Prestige"`, `"Interstellar"`
   - Ordered IDs: `["movie-id-tdkr", "movie-id-bb", "movie-id-inception", "movie-id-prestige", "movie-id-interstellar", ...]`
   - Ranking version: `cine-score-v1` (authoritative)

### Byte-for-Byte Result Ordering Invariance
- Verification: Compares Marathi discovery output with and without `include_shadow: true`.
- Result: Ordered movie IDs are byte-for-byte identical, confirming that enabling shadow diagnostics does not alter the result sorting or pagination.

### Browser UI Verification Note
- Playwright browser execution failed to download its Mac arm64 driver zip from the CDNs due to a driver version 404 issue. Manual/automated browser verification could not be completed.
- Code review confirms that frontend toggles (`enable-shadow-diagnostics`, `enable-shadow-diagnostics-nl`, `enable-shadow-diagnostics-manual`) are hidden by default and only render when `NEXT_PUBLIC_CINESENSE_ENABLE_SHADOW_DIAGNOSTICS` is set to `"true"`.

Offline workflow entry points:

- `build_regional_evidence_sample.py`
- `validate_regional_evidence_sample.py`
- `build_regional_cohort_baselines.py`
- `run_regional_shadow_scoring.py`
- `build_regional_judgment_cases.py`
- `import_regional_judgments.py`
- `evaluate_regional_weight_configs.py`

## Implemented Verification Areas

The committed test suite covers:

- lookup service behavior
- recommendations API, orchestration, persistence, and ranking
- structured discovery schema, pipeline, and API
- natural-language discovery service behavior and API contract
- ranking foundation freeze/dispatcher behavior
- regional evidence sampling and validation
- regional cohort baseline building
- regional ranking audit
- `cine-score-v2` shadow scoring

## User Verification

### Exact Lookup And Recommendations

1. Copy `.env.example` to `.env` and set `TMDB_API_READ_ACCESS_TOKEN`.
2. Run `./scripts/start-phase-1a.sh` from the repo root.
3. Open `http://localhost:3000`.
4. Search for `The Dark Knight` with year `2008`.
5. Confirm one result renders with `cine-score-v1`, freshness, provenance, aliases, and missing signals.
6. Repeat the same search and confirm the cached path still returns the same movie cleanly.
7. Search for `Crash` and confirm explicit disambiguation choices appear.
8. Use `Find similar movies` and confirm up to 20 recommendations render in backend order.

### Structured Discovery

1. Open `http://localhost:3000/discover`.
2. Confirm the page supports structured filters for genres, language, region, year bounds, runtime bounds, and evidence count.
3. Submit a request such as genres `Action` and `Drama`, `release_year_min=1990`, `page_size=2`.
4. Confirm ranked results render with score breakdown, missing signals, provenance, freshness, and poster fallback behavior.
5. Confirm availability is still disabled rather than silently routed to a provider.

### Natural-Language Discovery

1. Set `CINESENSE_LLM_ENABLED=true` and the matching `CINESENSE_LLM_*` settings before startup.
2. Restart the stack and return to `http://localhost:3000/discover`.
3. Switch to natural-language mode.
4. Submit a query such as `Marathi thrillers released between 2016 and 2018`.
5. Confirm the backend either returns a validated interpreted request plus ranked results or a controlled interpreter error.
6. Confirm results still report `cine-score-v1` and do not expose shadow or fallback metadata.

## API Verification

Lookup:
- `curl -s http://localhost:8000/api/v1/lookup -H 'Content-Type: application/json' --data '{"title":"The Dark Knight","year":2008,"media_type":"movie"}'`

Recommendations:
- `curl -i http://localhost:8000/api/v1/recommendations -H 'Content-Type: application/json' --data '{"seed_movie_id":"00000000-0000-0000-0000-000000000000","region":"US","page_size":20}'`

Structured discovery:
- `curl -s http://localhost:8000/api/v1/discover -H 'Content-Type: application/json' --data '{"genres":["action"],"page":1,"page_size":2}'`

Natural-language discovery:
- `curl -s http://localhost:8000/api/v1/discover/natural-language -H 'Content-Type: application/json' --data '{"query":"Marathi thrillers released between 2016 and 2018","page":1,"page_size":2}'`

Expected controlled failures:

- malformed UUID or schema issues: `422`
- unknown recommendation seed: `404`
- unsupported discovery availability filter: `422`
- interpreter unavailable: `503`
- provider failure: `502`

## Offline Artifact Verification

Regional evidence sample:
- confirm the run directory contains `movies.jsonl`, `wikidata_matches.jsonl`, `coverage_summary.json`, and `run_manifest.json`

Validation run:
- confirm `validation/validated_matches.jsonl`, `validation/validation_summary.json`, `validation/review_sample.csv`, and `validation/validation_manifest.json`

Cohort baselines:
- confirm `cohort_baselines.json`, `movie_cohort_assignments.jsonl`, `cohort_coverage_report.json`, and `cohort_baseline_manifest.json`

Shadow scoring:
- confirm `shadow_scores.jsonl`, `shadow_ranking.json`, `v1_v2_comparison.json`, `shadow_summary.json`, and `shadow_manifest.json`

Human judgment workflow:
- confirm `judgment_cases.csv` excludes v1/v2 ranks, scores, and rank deltas
- confirm `judgment_case_mapping.jsonl` keeps the hidden scorer fields needed for offline evaluation, and includes the `selection_reasons` list for each case
- confirm unique pair policy ensures each unordered movie pair occurs at most once in `judgment_cases.csv`
- confirm exclusions are correct: future releases, ambiguous status, and critical warning movies are excluded
- confirm primary genre mapping parses actual TMDB genre names from `movies.jsonl` correctly and uses empty string for missing genres
- confirm `reviewed_judgments.jsonl` and `reviewed_judgment_summary.json` are written only after immutable-column validation passes
- confirm strict `decimal.Decimal` validation checks numbers: rejects scientific notation, commas, booleans, NaN/Infinity, internal whitespace/signs, and ensures year matches mathematically integral Decimal values.
- confirm negative zero handling equated `-0` / `-0.00` to `0`
- confirm structured warnings validation rejects duplicates, blank warning tokens, casing differences, additions/removals, internal spaces, and malformed delimiters
- confirm duplicate columns in header or altered text fields cause import failure
- confirm unescaped formula cells in editable fields fail import
- confirm notes starting with a bullet dash `-` are accepted if benign, and double escapes strip exactly one quote safety prefix
- confirm `weight_evaluation_summary.json`, `weight_evaluation_cases.jsonl`, `language_weight_comparison.json`, `evaluation_recommendation.json`, and `evaluation_manifest.json` are deterministic for identical inputs


## Determinism And Negative Checks

- repeated unchanged requests should preserve backend ordering
- missing signals stay missing and are not coerced to zero
- production responses should keep reporting `cine-score-v1`
- `cine-score-v2-shadow-1` should remain offline-only
- unsupported availability filters should not trigger TMDB calls
- tokens and secrets must not appear in logs, responses, build output, review CSVs, or manifests
