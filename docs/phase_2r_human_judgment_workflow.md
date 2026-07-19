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
- **nullable_integer**: `movie_a_release_year`, `movie_b_release_year`. Accepts integer conversions like `2008` and `2008.0` as equivalent. Null values (`""` or empty cells) are matched. Rejects commas (e.g., `2,008`), scientific notation, booleans, and changed values.
- **nullable_decimal**: `movie_a_tmdb_rating`, `movie_b_tmdb_rating`. Accepts floats with different decimal precision (e.g., `7.5` and `7.500`). Rejects commas, scientific notation, and booleans.
- **structured_serialized_value**: `evidence_warnings`. Splitted by `|`, sorted, and compared semantically to prevent order-change errors.

### 2. Reviewer Notes CSV-Injection Safety
Reviewer notes are normalized using a reversible escape convention:
- **Escape Leading Apostrophe**: If the reviewer's note starts with `=, +, -, or @` (formula prefixes), it must be escaped with a leading apostrophe (e.g., `'- Stronger screenplay` or `'=SUM(1,2)`). The importer will automatically strip the leading apostrophe and store the intended string safely in the snapshot.
- **Benign Dashes/Signs**: Notes starting with a normal sign (like `- Stronger screenplay`) that do not look like executable formulas (not followed by digits/parentheses/symbols) are accepted without requiring an apostrophe escape.
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
