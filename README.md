# cineSense

Transparent, region-aware movie discovery with deterministic backend ranking and explicit data provenance.

Current status: Phase 1A MVP scaffold and exact-title lookup implementation as of July 18, 2026.

Implemented now:
- monorepo layout with `apps/web` and `services/api`
- FastAPI exact-title lookup endpoint at `POST /api/v1/lookup`
- PostgreSQL schema and Alembic migration for movies, aliases, external IDs, and observations
- TMDB-backed provider adapter behind a backend-only token boundary
- deterministic provisional `cine-score-v1`
- Next.js UI for lookup, disambiguation, score breakdown, missing signals, provenance, and freshness

Not implemented yet:
- Phase 1B recommendations
- non-TMDB providers
- authentication, payments, Redis, Celery, Kafka, Kubernetes, or LLM-authored ranking

Documentation map:
- `planning.md`: scope, phases, risks, status, open questions
- `designing.md`: system architecture and data model
- `verification.md`: acceptance checks and user verification steps
- `agentic.md`: LLM boundaries
- `tools.md`: provider adapter contracts
- `data_sources.md`: approved and prohibited sources
- `ranking.md`: `cine-score-v1` design
- `security_licensing.md`: security and licensing constraints
- `code_review.md`: review checklist
- `docs/plans/phase_1a_exact_lookup.md`: Phase 1A execution plan
- `docs/plans/phase_1b_seed_recommendations.md`: Phase 1B execution plan
- `docs/phase_1a_achievement.md`: current phase handoff and next-prompt seed
- `docs/chatgpt_codex_project_workflow.md`: how to move context between ChatGPT Projects and Codex
- `docs/decisions/0001_provider_first_ingestion.md`
- `docs/decisions/0002_field_level_freshness.md`
- `docs/decisions/0003_versioned_deterministic_ranking.md`

Repo layout:
- `apps/web`: Next.js frontend
- `services/api`: FastAPI backend, TMDB adapter, scoring, migrations, and tests
- `compose.yaml`: local PostgreSQL, API, and web orchestration
- `.env.example`: local environment variable template

Local run outline:
1. Copy `.env.example` to `.env`.
2. Replace `TMDB_API_READ_ACCESS_TOKEN` in `.env` with a real local token.
3. Run `./scripts/start-phase-1a.sh` from the repo root.
4. Open `http://localhost:3000`.

Default startup command after implementation:
- `./scripts/start-phase-1a.sh`
- Equivalent npm wrapper: `npm run start:phase-1a`
- This uses BuildKit/Bake for cached rebuilds, rebuilds only changed layers, starts PostgreSQL, applies the API migration automatically, then runs the API and web app.

What we are building right now:
- A Phase 1A exact movie-title lookup app.
- The frontend is a small Next.js form where a user enters title, optional year, and optional region.
- The backend is a FastAPI service that normalizes the request, checks PostgreSQL first, fetches from TMDB only when needed, persists the canonical movie plus provenance/freshness, and returns a provisional `cine-score-v1`.
- The current success case is one resolved movie detail card or a disambiguation list for ambiguous titles such as `Crash`.

How to check frontend and backend as a user:
1. Create `.env` from `.env.example` and set a real local `TMDB_API_READ_ACCESS_TOKEN`.
2. Run `./scripts/start-phase-1a.sh`.
3. Open the frontend in a browser and confirm the form shows `Title`, `Release year`, `Region`, and `Media type`.
4. Search for `The Dark Knight` with year `2008`.
5. Confirm the page shows one movie result with a score, freshness, provenance, aliases, and missing signals.
6. Repeat the same search and confirm the app still works and reports cached/local reuse rather than behaving like a blank first fetch.
7. Search for `Crash` and confirm the UI shows disambiguation choices instead of silently picking one movie.
8. Confirm the TMDB token never appears in the page, browser network payloads, or API response body.
