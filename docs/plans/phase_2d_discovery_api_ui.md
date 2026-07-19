# Phase 2D Discovery API + UI

## Goal

Expose the completed structured discovery pipeline through:
1. a public backend API
2. a manual-filter discovery page

## Phase 2D.1 Discovery API

- Add `POST /api/v1/discover`.
- Use the existing Phase 2A `DiscoveryRequest` directly as the request contract with no second validation schema.
- Route behavior:
  - validate with the existing schema only
  - call only the existing internal discovery orchestration
  - do not recalculate scores in the route
  - preserve backend result order
- Response shape:
  - `status`
  - `request`: normalized request payload
  - `results`: ranked discovery results
  - `page`:
    - `page`
    - `requested_page_size`
    - `returned_count`
    - `max_page_size: 20`
- Each result must include:
  - canonical movie ID
  - title
  - release year
  - original language
  - overview
  - poster URL
  - TMDB external ID
  - original provider position
  - `cine-score-v1` total
  - `cine-score-v1` component breakdown
  - missing signals
  - provenance
  - freshness
- Controlled API outcomes:
  - valid discovery: `200`
  - empty results: `200` with empty `results`
  - malformed or unrestricted request: `422`
  - `availability_required=true`: `422` with `unsupported_filter`
  - safe TMDB/provider failure: `502`
  - no token, raw payload, or internal exception leakage

## Phase 2D.2 Manual Filter UI

- Add a dedicated discovery route at `/discover`.
- Add simple navigation between:
  - `Exact Lookup`
  - `Discover Movies`
- Reuse existing web patterns where practical:
  - API base URL handling
  - loading / error / empty / success state handling
  - movie card and recommendation-style score/provenance/freshness presentation
  - poster fallback behavior
- Manual filters:
  - genres with multiple selection
  - original-language code
  - region code
  - release-year minimum and maximum
  - runtime minimum and maximum
  - minimum evidence count
  - page size capped at 20
- Availability handling:
  - present as unavailable or coming later
  - do not submit unsupported availability filters
  - leave regional streaming availability for Phase 2G
- UI behavior:
  - submit only the structured Phase 2A request
  - no free-text or LLM input
  - preserve backend ranking order
  - display no more than 20 results
  - show score, breakdown, missing signals, provenance, and freshness
  - next / previous page controls
  - reset filters
  - responsive and consistent with the current visual system

## Out Of Scope

- LLM interpreter
- mood and pace input
- streaming availability
- new ranking version
- extra providers
- authentication
- broad frontend redesign

## Acceptance Criteria

### API

- valid discovery request returns `200` with normalized request, ranked results, and pagination
- normalization matches the Phase 2A schema exactly
- pagination reflects requested page and page size with maximum page size `20`
- empty result set returns `200` with an empty list
- malformed and unrestricted requests return controlled `422`
- `availability_required=true` returns controlled `422 unsupported_filter`
- safe provider failure returns controlled `502` with no secret leakage
- repeated unchanged inputs preserve deterministic ordering

### UI

- filters submit a structured Phase 2A request only
- multiple genres can be selected and submitted together
- normalized request behavior is reflected through the backend response
- results render in backend order
- next / previous page controls work without client-side reordering
- reset clears filters and result state
- loading, error, and empty states are explicit
- missing poster and missing signals render safely
- no secrets or raw provider payloads are exposed in the client

## Verification Plan

### Phase 2D.1

- focused mocked API tests
- normal backend regression suite
- live curl check after implementation

### Phase 2D.2

- focused frontend tests if an existing framework is available
- frontend production build
- manual browser verification

## How To Check As A User

### API

1. Start the backend with the normal local command for the repo root workflow.
2. Send a valid request to `POST /api/v1/discover`.
3. Confirm the response includes the normalized request, paginated results, score breakdown, missing signals, provenance, and freshness.
4. Send an unrestricted request and confirm a controlled `422`.
5. Send `availability_required=true` with `region` and confirm a controlled `422 unsupported_filter`.
6. Send a valid request expected to return no matches and confirm `200` with an empty `results` list.
7. Repeat the same valid request and confirm the order is identical.

### UI

1. Open `/discover`.
2. Confirm the UI exposes only manual structured filters and no free-text discovery input.
3. Submit a filter combination with multiple genres and confirm ranked results render.
4. Confirm each result shows poster or fallback, title, release year, original language, score, breakdown, missing signals, provenance, and freshness.
5. Use next / previous page controls and confirm the page changes while preserving backend order.
6. Use reset and confirm filters and displayed results clear.
7. Trigger an empty-result case and confirm the empty state is shown.
8. Trigger a safe error case and confirm the UI shows a safe error state without leaked internals.

## Documentation Ownership

During implementation:
- update `verification.md`
- update `README.md` only when `/discover` becomes runnable
- create `docs/phase_2d_achievement.md` only when both 2D.1 and 2D.2 are verified

## Locked Decisions

- `POST /api/v1/discover` is the public Phase 2D.1 endpoint.
- The request contract is the existing Phase 2A `DiscoveryRequest` with no duplicate validation layer.
- Discovery API ranking stays backend-owned and reuses existing internal orchestration and `cine-score-v1`.
- `/discover` is the Phase 2D.2 route.
- Availability remains disabled in the manual UI until Phase 2G.

## Next Prompt Seeds

### Phase 2D.1 API

Implement Phase 2D.1 only:
- add `POST /api/v1/discover`
- reuse the existing `DiscoveryRequest`
- add response schema(s) only as needed for the public API shape
- call only the existing internal discovery orchestration
- add focused mocked API tests
- run the focused API tests and the normal backend regression suite
- do not change frontend code

### Phase 2D.2 UI

Implement Phase 2D.2 only:
- add `/discover`
- add simple navigation between exact lookup and discover movies
- build a manual structured-filter page that calls `POST /api/v1/discover`
- reuse existing UI patterns and components where practical
- add focused frontend tests only if the current toolchain already supports them
- run the frontend build and perform manual verification
- do not change backend discovery ranking or provider logic
