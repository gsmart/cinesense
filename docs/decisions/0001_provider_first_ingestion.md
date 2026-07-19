# ADR 0001: Provider-First Ingestion

## Status

Accepted

## Decision

The system will resolve and ingest movie data through explicit provider adapters rather than direct scraping or ad hoc payload handling.

## Why

- preserves provenance and legality
- keeps normalization centralized
- makes future provider swaps additive instead of invasive
- supports deterministic refresh and retry policy

## Consequences

- every external fetch must pass through an adapter contract
- prohibited sources remain blocked even if technically reachable
- new providers require documentation updates before activation

