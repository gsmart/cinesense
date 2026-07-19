# ADR 0002: Field-Level Freshness

## Status

Accepted

## Decision

Freshness is tracked at the observation or signal level, not only at the movie row level.

## Why

- different signals age at different rates
- partial refresh is cheaper than whole-record invalidation
- missing or failed fields can stay explicit without hiding fresher fields

## Consequences

- observation storage needs source, timestamps, hashes, and freshness windows
- API responses must summarize freshness per signal set
- ranking must tolerate mixed freshness states

