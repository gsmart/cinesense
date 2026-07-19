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
- Tests: non-trivial logic leaves a runnable check behind
