# Tools

## Live Provider Adapters

### TMDB Adapter

Committed application code uses TMDB for:

- exact title search
- movie detail bundles
- seed recommendations
- structured discovery candidate retrieval

Operational rules:

- explicit HTTP timeouts through `httpx`
- bounded calls only
- normalized outputs returned to service code
- controlled provider-failure summaries instead of raw payload leakage

Known current boundary:

- `availability_required=true` is intentionally unsupported in discovery and returns a controlled failure

## Optional Interpreter Tooling

The natural-language interpreter is backend-wrapped, not user-directed tool use.

Inputs:
- one free-text discovery query plus page controls

Outputs:
- one untrusted structured payload candidate

Controls:

- disabled unless `CINESENSE_LLM_ENABLED=true`
- base URL, API key, model, and timeout come from backend settings
- every interpreted payload still goes through deterministic schema validation

## Offline Regional Analysis Scripts

### `build_regional_evidence_sample.py`

Side effects:
- TMDB and Wikidata fetches
- writes artifact directories under `/tmp` unless overridden

Outputs:
- evidence sample JSONL files
- coverage summary JSON
- run manifest JSON

### `validate_regional_evidence_sample.py`

Side effects:
- local artifact reads only
- writes validation JSONL, CSV, and manifest outputs

Checks:
- file integrity
- secret leakage patterns
- match classification
- manual review sample generation

### `build_regional_cohort_baselines.py`

Side effects:
- local artifact reads only
- writes cohort baseline JSON/JSONL artifacts

Outputs:
- cohort hierarchy
- fallback selections
- readiness and recommendation summaries

### `run_regional_shadow_scoring.py`

Side effects:
- local artifact reads only
- writes shadow score, comparison, ranking, summary, and manifest outputs

Outputs:
- `cine-score-v2-shadow-1`
- `cine-score-v1` comparison rows
- cohort fallback diagnostics

### `audit_regional_ranking.py`

Purpose:
- synthetic/offline ranking audit for comparison and status reporting

Boundary:
- does not activate production ranking changes

## Side-Effect Rules

- application code may persist canonical movie and observation data in PostgreSQL
- offline analysis scripts write file artifacts, not production DB rows
- no tool in the committed repo stages, commits, or publishes data externally
