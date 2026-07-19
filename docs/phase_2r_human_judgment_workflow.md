# Phase 2R.3B Human Judgment Workflow

Current workspace state adds an offline-only multilingual review workflow on top of shadow evaluation:

- blinded pairwise judgment-case generation from evaluated regional shadow artifacts
- strict import validation for completed review CSVs
- immutable reviewed-judgment snapshots
- bounded `cine-score-v2` candidate-weight evaluation against reviewed judgments

## Hardened CSV Workflow (Usability Hardening Patch)

To accommodate benign spreadsheet formatting changes introduced by standard tools (like Excel, Google Sheets, and Numbers) without weakening tamper protection:

### 1. Schema-Based Type-Aware Column Validation
Every immutable column is validated against a strict schema:
- **exact_identifier**: `judgment_case_id`, `movie_a_tmdb_id`, `movie_b_tmdb_id`. Must be exactly identical (no whitespace changes allowed).
- **exact_text**: `case_type`, `language`, `movie_a_vote_count`, `movie_b_vote_count`, `movie_a_popularity`, `movie_b_popularity`, `movie_a_cohort_level`, `movie_b_cohort_level`, `movie_a_identity_status`, `movie_b_identity_status`. Exact string matching.
- **normalized_text**: `movie_a_title`, `movie_b_title`, `movie_a_primary_genre`, `movie_b_primary_genre`. Ignores leading and trailing whitespaces (e.g., `"  Inception  "` matches `"Inception"`).
- **nullable_integer**: `movie_a_release_year`, `movie_b_release_year`. Validated using strict `decimal.Decimal` conversion. Accepts `2008`, `2008.0`, and `2008.00` if the value is mathematically integral. Rejects non-integers (e.g., `2008.5`), commas (e.g., `2,008`), scientific notation, booleans (`True`/`False`), NaN/Infinity, and internal spaces or signs (e.g., `+-2008`, `+ 2008`). Null values (`""`) match only if the original generated value is null. Null-to-zero and zero-to-null changes fail.
- **nullable_decimal**: `movie_a_tmdb_rating`, `movie_b_tmdb_rating`. Validated using strict `decimal.Decimal` equality. Tolerates trailing decimal zeros (e.g. `7.5` matches `7.500`). Rejects commas, scientific notation, booleans, NaN/Infinity, and internal spaces or signs. Nulls must match exactly.
- **structured_serialized_value**: `evidence_warnings`. Tokens are split by `|`. Validation strictly rejects: duplicate warning tokens, blank warning tokens, changed casing, added/removed warnings, malformed delimiters (e.g. commas), and whitespace inside warning identifiers. No silent deduplication of tampered values occurs.
- **negative_zero_handling**: Negative zero representations (e.g. `-0`, `-0.00`) are correctly parsed and mathematically equated to zero (`0`).

### 2. Reviewer Notes CSV-Injection Safety
Reviewer notes are normalized using a reversible escape convention:
- **Escape Leading Apostrophe**: If the reviewer's note starts with `=, +, -, or @` (formula prefixes), or with a single quote `'` that is escaping one of those prefixes, it must be escaped with a leading apostrophe (e.g., `'- Stronger screenplay` or `'=SUM(1,2)`, or `''- Escaped twice`). The importer removes exactly one recognized safety prefix (a leading apostrophe followed by `=, +, -, @` or `'`) and does not repeatedly strip apostrophes.
- **Benign Dashes/Signs**: Notes starting with a normal sign (like `- Stronger screenplay`) that do not look like executable formulas (not followed by digits/parentheses/symbols) are accepted without requiring an apostrophe escape.
- **Literal quotes**: A legitimate note that begins with a literal apostrophe (e.g., `'Literal quote`) is not altered.
- **Rejection**: Unescaped notes starting with actual formula indicators (like `=1+2`, `@macro`) are strictly rejected.

### 3. Reviewer Instructions
* **Excel / Numbers / Google Sheets**:
  * If entering notes starting with a dash (e.g., bullet point `- Bullet`), you can type them directly, but to be completely safe, write them starting with a single quote: `'- Bullet`.
  * If writing a note starting with `=` or `@`, always prefix it with a single quote: `'=Note` or `'@Note`.
  * Do not modify the headers or any other columns.
  * Duplicate headers or modified case IDs will cause the import command to fail.

What is still true:

- production ranking remains `cine-score-v1`
- `cine-score-v2` remains shadow-only
- no API or frontend surface was added for this workflow
- no candidate configuration is auto-approved for production

Recommended next prompt seed:

- use a real completed reviewer CSV and ask for a focused comparison of control versus candidate weight configurations across Marathi, Malayalam, and Tamil
