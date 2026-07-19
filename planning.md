# Planning

Current date: July 19, 2026
Inspected branch: `main`
Inspected HEAD: `5f6b8e00e0810bcf05f4cb7f8f46a2fbf20a8f4b`
Worktree note: uncommitted files exist for regional shadow evaluation and are not treated as completed repository milestones

## Current Phase

Current phase:
- Phase 2R shadow-scoring prototype work is implemented provisionally

Last completed phase:
- Phase 2R ranking foundation and offline `cine-score-v2` shadow scoring prototype at commit `5f6b8e0`

Immediate next phase:
- evaluate the shadow pipeline, decide whether the regional evidence and cohort baseline gates justify deeper `cine-score-v2` work, and keep production on `cine-score-v1` until that evidence exists

Current blockers:
- no approved path to activate `cine-score-v2` in production
- regional evidence workflows still depend on manual review outcomes and offline artifacts
- natural-language discovery is optional and unavailable unless explicit LLM settings are configured

## Phase Status

| Phase | Status | Notes |
| --- | --- | --- |
| Phase 0 documentation and constraints | COMPLETED | Repo is implemented and no longer in Phase 0-only state |
| Phase 1A exact title lookup | COMPLETED | Commit `d1d0fe4`; lookup, cache reuse, persistence, disambiguation |
| Phase 1B seed recommendations | COMPLETED | Commits `4d4e994` through `02e70a8`; API and UI verified |
| Phase 2A structured discovery contract | COMPLETED | Commit `c75cdb1`; provider-neutral schema and validation |
| Phase 2B discovery retrieval | COMPLETED | Commit `8504efc`; bounded TMDB discovery mapping |
| Phase 2C discovery persistence and deterministic ranking | COMPLETED | Commit `8504efc`; canonical reuse and ranking integration |
| Phase 2D public discovery API and manual UI | COMPLETED | Commits `ccf2079`, `01500fd`; `/api/v1/discover` and `/discover` |
| Phase 2E natural-language discovery interpreter | IMPLEMENTED_PROVISIONALLY | Commits `dea65a5`, `e091741`; backend remains authoritative, feature depends on LLM config |
| Phase 2F clarification and editable fallback | PLANNED | No committed implementation |
| Phase 2G availability refinement | PLANNED | Availability remains disabled/unsupported |
| Phase 2R ranking foundation | COMPLETED | Commit `50556d4`; shared ranking dispatcher, production still `cine-score-v1` |
| Regional evidence sampling and Wikidata enrichment | IMPLEMENTED_PROVISIONALLY | Commits `99b34ce`, `4e135ac`; offline artifact builder only |
| Expanded regional evidence review gate | IMPLEMENTED_PROVISIONALLY | Commit `7a1b61e`; validation and review sample output exist, approval remains manual |
| Regional cohort baseline builder | IMPLEMENTED_PROVISIONALLY | Commit `958b7ce`; offline baseline artifacts and gate status exist |
| `cine-score-v2` shadow scoring prototype | IMPLEMENTED_PROVISIONALLY | Commit `5f6b8e0`; offline comparison only, production unaffected |
| Multilingual shadow evaluation | IN_PROGRESS | Uncommitted worktree files exist, not part of `HEAD` |

## Completed Milestones

- Phase 1A exact lookup shipped with persistence, freshness, disambiguation, and `cine-score-v1`
- Phase 1B seed recommendations shipped through API and UI
- Phase 2 discovery shipped in three slices: schema, backend pipeline, public API/manual UI
- natural-language discovery was added without moving ranking authority out of the backend
- versioned ranking dispatch was introduced without changing public production ordering
- offline regional evidence sampling, validation, cohort baselines, and `cine-score-v2` shadow scoring were added behind scripts and artifacts rather than public endpoints

## Remaining Milestones

- decide whether Phase 2F clarification/editable fallback is still needed after the current natural-language flow
- implement availability integration only through an approved provider path
- define whether `cine-score-v2` stays offline, becomes a wider shadow experiment, or is abandoned
- if `cine-score-v2` survives, add a reviewed activation plan rather than switching production ordering ad hoc

## Key Risks

- the offline evidence and baseline pipeline can produce artifacts without proving they are strong enough for production ranking changes
- optional LLM interpretation increases surface area for invalid or overly broad discovery requests, even though backend validation blocks them
- TMDB remains the only live provider path in committed application code
- source licensing and attribution requirements still gate any commercial or broader launch claims

## Open Decisions

- whether to keep investing in `cine-score-v2` beyond offline shadow analysis
- whether to add more approved sources beyond TMDB and Wikidata-derived metadata enrichment
- whether discovery needs a Phase 2F clarification UX or whether the current structured plus optional natural-language split is sufficient
- what reviewed threshold should be required before any production ranking activation change
