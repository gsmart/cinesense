# Security And Licensing

## Secrets

- `TMDB_API_READ_ACCESS_TOKEN` stays server-side only
- optional `CINESENSE_LLM_API_KEY` stays server-side only
- secrets must not appear in frontend bundles, API responses, logs, manifests, or review files
- regional evidence validation includes secret-pattern checks against artifact inputs

## Prohibited Access

- no IMDb website scraping
- no Rotten Tomatoes website scraping
- no arbitrary internet scraping
- no undocumented provider path in application code

## Source Restrictions

- TMDB is the active live application source
- Wikidata is restricted to offline evidence enrichment
- any future licensed critic or availability source must be documented before activation
- manual review files and CSV inputs do not create a blanket right to publish or commercialize those artifacts

## Artifact Safety

Offline regional workflows create local artifacts containing:

- movie metadata samples
- match classifications
- manual review CSVs
- readiness summaries
- shadow-score comparisons

These artifacts should be treated as internal engineering data. They are not production APIs and should not be exposed casually.

## Review-File Safety

- review CSVs must stay free of secrets
- reviewer notes are human-authored local inputs and should be handled as internal files
- validation should remain deterministic even when review input is absent or incomplete
- reviewer-facing CSV exports must avoid spreadsheet-formula injection in editable cells
- reviewed imports must reject immutable-column tampering and formula-like reviewer input
- **Spreadsheet Formula Safety**: Reviewer notes starting with `=, +, -, or @` must be escaped using a leading apostrophe `'`. The importer automatically unescapes these notes by stripping exactly one leading apostrophe prefix (protecting Excel/Sheets from executing formulas). Double escaped safety prefixes (e.g. starting with `''-`) strip exactly one leading apostrophe. Literal quotes without formula prefixes are left unaltered. Unescaped formula blocks are rejected to prevent CSV-injection vectors. Benign dash-prefixed text notes are accepted directly.

## Commercial Launch Gates

Before any broader launch:

- confirm all live and offline sources are licensed for the intended use
- confirm required attribution is implemented
- confirm optional LLM provider usage is acceptable for the target environment
- confirm `cine-score-v2` remains disabled unless a reviewed activation decision exists
- confirm internal review artifacts are not being exposed as product data
