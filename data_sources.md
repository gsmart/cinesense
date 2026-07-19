# Data Sources

## Approved Source Categories

- `OFFICIAL_API`
- `OFFICIAL_DATASET`
- `LICENSED_FEED`
- `MANUAL_FIXTURE`
- `PROHIBITED`

`PERMITTED_SCRAPE` is not used by the committed repository state.

## Current Source Register

### TMDB API

Access mode:
- `OFFICIAL_API`

Used now for:
- exact title lookup
- movie detail enrichment
- seed recommendations
- structured discovery retrieval
- regional evidence sampling

Stored/provenance fields:
- source name
- source movie ID
- normalized values
- timestamps and freshness windows
- source URL when available
- raw response hashes where the workflow records them

Status:
- active and required for live application behavior

### Wikidata SPARQL

Access mode:
- `OFFICIAL_API`

Used now for:
- offline regional evidence enrichment only

Status:
- implemented in the evidence pipeline, not exposed through product APIs

Rules:
- bounded retries
- explicit user agent
- artifact-based output with hashes and manifest metadata

### National Film Awards CSV/Input File

Access mode:
- `MANUAL_FIXTURE` unless a separately approved source contract is documented

Used now for:
- optional offline recognition matching in the regional evidence pipeline

Status:
- optional artifact input, not a live provider integration

### IMDb Official Datasets Or Licensed Access

Access mode:
- `OFFICIAL_DATASET` or `LICENSED_FEED`

Status:
- not implemented in committed application code

### IMDb Website Scraping

Access mode:
- `PROHIBITED`

Status:
- prohibited

### Rotten Tomatoes Website Scraping

Access mode:
- `PROHIBITED`

Status:
- prohibited

### Rotten Tomatoes Licensed Feed

Access mode:
- `LICENSED_FEED`

Status:
- not implemented

### Manual Fixtures

Access mode:
- `MANUAL_FIXTURE`

Used now for:
- deterministic tests
- synthetic ranking audits
- optional offline review inputs
- blinded human ranking judgment CSVs and reviewed snapshots

## Storage And Attribution Rules

- live product behavior stores normalized provider observations plus provenance
- missing data stays missing
- source identity and fetch timing are preserved for auditability
- offline artifact runs store input/output hashes and source metadata in manifests
- regional evidence review files must be treated as local artifacts, not published user-facing data
- human ranking judgment files are local reviewer artifacts and must not be treated as provider truth or product-facing metadata

## Current Constraints

- TMDB is the only live application provider path
- Wikidata is limited to offline enrichment flows
- critic-consensus sources remain unimplemented
- availability integration remains unimplemented in live discovery
