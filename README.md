# cineSense

Transparent, region-aware movie discovery with deterministic backend ranking and explicit data provenance.

Current status: Phase 0 documentation only as of July 18, 2026. The repository currently defines architecture, data contracts, ranking boundaries, provider rules, and verification criteria. It does not yet contain implementation code.

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
- `docs/decisions/0001_provider_first_ingestion.md`
- `docs/decisions/0002_field_level_freshness.md`
- `docs/decisions/0003_versioned_deterministic_ranking.md`

Immediate next step after Phase 0: implement Phase 1A exact-title lookup only, using the documented constraints and acceptance criteria.

