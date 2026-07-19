# Agentic

## LLM Role

The LLM is optional and non-authoritative.

Committed code uses it only for one bounded job:
- interpreting a natural-language movie discovery query into the existing structured discovery request shape

The LLM does not:

- compute authoritative movie scores
- choose final ordering outside backend ranking code
- invent missing metadata
- bypass request validation
- call arbitrary external providers
- participate in the offline regional evidence, baseline, or shadow-scoring calculations

## Deterministic Backend Ownership

Backend code remains authoritative for:

- exact lookup resolution
- disambiguation thresholds
- canonical persistence and freshness reuse
- provider orchestration
- structured discovery validation
- ranking version dispatch
- production `cine-score-v1` calculation
- all offline regional evidence validation, cohort baseline, and shadow-score calculations

## Natural-Language Boundary

The natural-language path is deliberately narrow:

1. the interpreter receives a free-text query
2. it returns an untrusted JSON-like payload
3. the backend validates that payload through the same `DiscoveryRequest` schema as manual discovery
4. invalid, overly broad, or unsupported interpretations are rejected
5. successful requests reuse the normal deterministic discovery pipeline

This keeps the LLM at the intent-parsing edge, not in ranking or retrieval authority.

## Tool And Provider Boundaries

- live application provider calls are routed through approved backend adapters only
- the committed application adapter is TMDB
- Wikidata is used in offline evidence enrichment only
- retries and timeouts stay bounded in code, not open-ended
- no scraping path is authorized

## Non-Goals

- no LLM-authored ranking
- no conversational answer generation that replaces search, retrieval, or ranking
- no hidden client-side ranking adjustments
- no arbitrary internet research inside the product runtime
