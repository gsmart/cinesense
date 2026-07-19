# ADR 0003: Versioned Deterministic Ranking

## Status

Accepted

## Decision

Ranking is computed in backend code with an explicit version identifier such as `cine-score-v1`.

## Why

- makes result changes explainable
- supports regression fixtures
- prevents silent formula drift
- keeps the LLM out of authoritative ranking

## Consequences

- every formula change requires a new version
- API payloads must expose ranking version
- regression checks become part of definition of done for ranking changes

