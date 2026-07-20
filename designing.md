# Designing

## Runtime Architecture

The committed repository has three runtime surfaces and one offline analysis track:

- Next.js web app in `apps/web`
- FastAPI backend in `services/api`
- PostgreSQL backing store configured through `compose.yaml`
- offline regional analysis scripts under `services/api/scripts`

The backend owns canonical resolution, persistence, freshness evaluation, ranking, and request validation. The frontend submits requests and renders backend outputs without re-ranking them.

## Implemented Request Flows

### Exact Lookup

1. Normalize title and region.
2. Search canonical movies plus aliases in PostgreSQL.
3. Reuse fresh or stale-usable local rows first.
4. Fall back to TMDB title search only when local resolution is insufficient.
5. Persist canonical movie, aliases, external IDs, and observations.
6. Compute ranking through the shared dispatcher.
7. Return one resolved movie or explicit disambiguation choices.

### Seed Recommendations

1. Resolve the seed movie from canonical storage.
2. Use the TMDB external ID to fetch bounded recommendation candidates.
3. Reuse or upsert canonical movie rows for candidates.
4. Rank deterministically through the shared ranking input/dispatcher path.
5. Return up to 20 results with provenance, freshness, and score breakdown.

### Structured Discovery

1. Validate a provider-neutral `DiscoveryRequest`.
2. Map neutral filters to TMDB Discover privately inside the adapter.
3. Treat unsupported availability filters as controlled failures instead of provider calls.
4. Persist or reuse canonical candidates.
5. Rank through the shared ranking path.
6. Return paginated results through `POST /api/v1/discover`.

### Natural-Language Discovery

1. Accept a free-text discovery request.
2. Route it through the optional `NaturalLanguageDiscoveryInterpreter`.
3. Validate the interpreted payload with the same `DiscoveryRequest` schema as structured discovery.
4. Reject invalid or unrestricted interpretations with controlled statuses.
5. Reuse the structured discovery pipeline unchanged for actual retrieval and ranking.

## Persistence Model

The single Alembic migration and SQLAlchemy models back these core entities:

- `movies`
- `movie_aliases`
- `external_ids`
- `observations`

This model is still movie-centric. The newer regional evidence and shadow-ranking work does not add relational schema yet; it writes offline JSON, JSONL, CSV, and manifest artifacts instead.

## Ranking Boundary

Production ranking remains backend-owned and deterministic:

- all application ranking call sites build one shared ranking input
- ranking dispatch is versioned internally
- active production version is `cine-score-v1`
- public API payloads still expose the applied score as `score`, `score_version`, `score_components`, and `missing_signals`

### Local Shadow Diagnostics
For local development, client requests can submit `include_shadow: bool = False`. If this flag is `true`, and local shadow diagnostics are enabled:
- The backend performs shadow comparison against the current `cine-score-v2-shadow-1` baseline artifacts.
- The returned movie objects include a `shadow_comparison: ShadowComparisonResponse` block.
- `ShadowComparisonResponse` fields: `authoritative` (always `false`), `shadow_only` (always `true`), `v1_score`, `v2_score`, `v1_rank`, `v2_rank`, `rank_movement`, `score_delta`, `score_version`, `evidence_gate`, `review_status` (defaults to `"PENDING"`), `activation_eligible` (defaults to `false`), `ineligible_reason`, and `warnings`.
- If `include_shadow: true` is requested when diagnostics are disabled, the server returns a `403 Forbidden` error.
- **Strict Invariance**: Under no circumstances does the shadow score or rank alter the top-level result order or pagination; sorting is strictly preserved according to `cine-score-v1`.

## Regional Evidence Pipeline

The committed offline pipeline is artifact-based:

1. `build_regional_evidence_sample.py`
   - samples TMDB discovery candidates by language
   - enriches them with Wikidata matches
   - optionally merges National Film Awards CSV records
   - writes run manifests plus coverage summaries
2. `validate_regional_evidence_sample.py`
   - validates evidence artifacts
   - scans for integrity and secret leakage issues
   - emits validated matches, review samples, and validation summaries
3. `build_regional_cohort_baselines.py`
   - groups validated movies into language/era/genre fallback cohorts
   - emits cohort baseline artifacts and gate/readiness summaries
4. `run_regional_shadow_scoring.py`
   - computes offline `cine-score-v2-shadow-1`
   - compares shadow ordering against a `cine-score-v1` proxy
   - emits ranking, comparison, summary, and manifest outputs
5. human-judgment workflow
   - `build_regional_judgment_cases.py` reads evaluated shadow artifacts and generates blinded multilingual pairwise review cases plus a machine-only mapping
   - `import_regional_judgments.py` validates a completed review CSV against immutable generated metadata and writes an immutable reviewed snapshot
   - `evaluate_regional_weight_configs.py` reuses the shadow scorer against a bounded weight grid and compares each configuration to reviewed judgments

These flows are deterministic and file-backed, not service-backed.

## Evidence And Baseline Boundaries

- TMDB remains the live provider for application requests
- Wikidata is used only in the offline evidence workflow
- manual review remains an explicit gate in the validation flow
- baseline readiness and shadow approval are computed as artifact statuses, not production flags
- no database persistence exists yet for review outcomes, cohort baselines, or shadow comparison runs

## Frontend Surface

The frontend currently exposes:

- `/` for exact lookup and follow-on recommendations
- `/discover` for structured discovery and natural-language discovery modes
- shared movie cards, provenance, freshness, missing-signal, and score-breakdown rendering

The UI preserves backend result order and does not calculate its own ranking.

## Human Judgment Boundaries

- reviewer-facing CSVs intentionally exclude v1/v2 ranks, scores, rank deltas, and weight configuration identifiers
- pairwise comparison is the primary review unit even when cases are sampled from top-k, disagreement, fallback, or confidence diagnostics
- reviewer-editable cells are limited to preference, confidence, reason code, and notes
- reviewed imports fail on immutable-column tampering, missing or duplicate case IDs, invalid reviewer values, and formula-like spreadsheet content
- reviewed snapshots and candidate-weight evaluation remain file-backed and `activation_eligible=false`
