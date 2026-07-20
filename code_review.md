# Code Review

Review against the current implemented platform, not the old Phase 1A-only scope.

- Scope: confirm the change matches the documented phase or explicitly calls out a new one
- Ranking: keep production ranking backend-owned, deterministic, and versioned
- `cine-score-v1`: no silent behavior changes without a version bump and regression coverage
- Natural-language discovery: interpreter output must remain untrusted and pass through the same schema validation as structured discovery
- Discovery: unsupported availability filters must stay controlled and must not leak into provider calls
- Providers: only approved adapters and documented sources are used
- Provenance: external signals and offline artifacts keep source identity, timestamps, and hashes where expected
- Persistence: canonical movies, aliases, external IDs, and observations must stay deduplicated
- Security: no token leakage in logs, responses, manifests, or review files
- Offline workflows: evidence validation, cohort baselines, and shadow scoring must not mutate production ranking state
- Human judgment workflow: case generation must enforce unique movie pairs (unordered), filter out future/unreleased titles, exclude ambiguous statuses or critical warnings, carry TMDB genres from source evidence correctly, and map multiple selection reasons; blinded reviewer CSVs must exclude anchoring scorer fields and reviewed imports must enforce immutable generated metadata using strict Decimal conversions, strict structured warnings validation (rejecting duplicates and blanks), duplicate column checks, and formula note safety escapes.
- Tests: non-trivial logic leaves a runnable check behind
- Shadow Diagnostics: verify that `include_shadow` and the UI toggle are gated by `CINESENSE_ENABLE_SHADOW_DIAGNOSTICS` and `NEXT_PUBLIC_CINESENSE_ENABLE_SHADOW_DIAGNOSTICS`, that enabling diagnostics has zero effect on movie sorting or pagination (order must remain identical), and that shadow outputs are clearly marked non-authoritative and shadow-only.
