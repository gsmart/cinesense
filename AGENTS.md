# AGENTS.md

Phase 1A exact-title lookup is now active. You may implement application code, install the minimum required packages, run Docker Compose, create PostgreSQL migrations, and call only approved provider APIs through backend adapters. Do not request credentials in chat, expose secrets in logs or code, scrape sites, modify `.codex/config.toml`, or implement work outside Phase 1A without explicit user approval.

Primary document ownership:
- `README.md`: project overview and documentation map
- `planning.md`: phases, scope, status, risks, open questions
- `designing.md`: architecture, data model, cache/freshness, API boundaries
- `verification.md`: checks, test scenarios, user verification steps
- `agentic.md`: LLM boundaries and deterministic backend ownership
- `tools.md`: provider/tool contracts, limits, retries, side effects
- `data_sources.md`: source legality, attribution, freshness, storage rules
- `ranking.md`: versioned scoring model and missing-data policy
- `security_licensing.md`: secrets, prohibited access, retention, launch gates
- `code_review.md`: review checklist
- `docs/plans/*.md`: per-phase execution plans
- `docs/decisions/*.md`: ADRs for locked architectural decisions

Definition of done for Phase 1A:
- Exact movie-title lookup works end to end for `movie` media type.
- Local PostgreSQL storage is checked first and reuses fresh data.
- TMDB fetches run only through approved backend adapters.
- Canonical movie rows, aliases, external IDs, observations, provenance, freshness, and `cine-score-v1` are persisted and returned.
- Ambiguous titles return explicit disambiguation choices.
- The web UI can submit a lookup and render one detail result with score breakdown, missing signals, source, and freshness.
- Small runnable checks exist for non-trivial logic.

Permanent constraints:
- No IMDb scraping.
- No Rotten Tomatoes scraping.
- No unrestricted internet scraping or ad hoc provider calls.
- No LLM-authored ranking or fabricated missing values.
- No authentication, payments, Redis, Celery, Kafka, Kubernetes, vector databases, or Phase 1B recommendation work.
- Never ask the user to paste API tokens into chat or store them in tracked files.

Standard practice:
- Keep `README.md` current with a short plain-English summary of what the repo currently builds.
- Keep `verification.md` current with explicit user-facing checks for frontend and backend behaviour, not just automated tests.
- When implementation changes the runnable flow, update the local run steps and "how to check as a user" instructions in the same task.
- Every runnable implementation phase should preserve one obvious startup command or script from the repo root. If the startup flow changes, update that command immediately.
- After a phase or meaningful feature is working, leave one short handoff/achievement note under `docs/` that records what works, how it was verified, known gaps, and the recommended next prompt seed.
- Treat ChatGPT Projects as the planning/memory layer and Codex as the execution layer. Keep a repo-backed handoff artifact under `docs/` so context can move between them without relying on undocumented sync behaviour.

Useful commands:
- `pwd`
- `git rev-parse --show-toplevel`
- `git branch --show-current`
- `git status --short`
- `rg --files -g 'AGENTS.md' -g '!node_modules' -g '!dist' -g '!build'`
- `rg --files -g '*.md' -g '!node_modules' -g '!dist' -g '!build'`
