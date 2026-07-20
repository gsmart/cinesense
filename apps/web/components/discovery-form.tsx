"use client";

import type { CSSProperties, FormEvent } from "react";
import { useState } from "react";

import type {
  ControlledErrorResponse,
  DiscoveryNormalizedRequest,
  DiscoveryRequestPayload,
  DiscoveryResponse,
  NaturalLanguageDiscoveryRequestPayload,
  NaturalLanguageDiscoveryResponse,
} from "@/lib/types";

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const showDiagnosticsToggle = process.env.NEXT_PUBLIC_CINESENSE_ENABLE_SHADOW_DIAGNOSTICS === "true";
const examplePrompts = [
  "Marathi thrillers released between 2016 and 2018",
  "English science-fiction movies after 2015 under 130 minutes",
  "Hindi comedy movies from the 2000s",
] as const;
const genreOptions = [
  ["action", "Action"],
  ["adventure", "Adventure"],
  ["animation", "Animation"],
  ["comedy", "Comedy"],
  ["crime", "Crime"],
  ["documentary", "Documentary"],
  ["drama", "Drama"],
  ["family", "Family"],
  ["fantasy", "Fantasy"],
  ["history", "History"],
  ["horror", "Horror"],
  ["music", "Music"],
  ["mystery", "Mystery"],
  ["romance", "Romance"],
  ["science-fiction", "Science Fiction"],
  ["thriller", "Thriller"],
  ["tv-movie", "TV Movie"],
  ["war", "War"],
  ["western", "Western"],
] as const;

type DiscoveryMode = "natural-language" | "manual";
type DiscoveryStatus = "idle" | "loading" | "paging" | "error" | "success";
type DiscoveryFilters = {
  genres: string[];
  originalLanguage: string;
  region: string;
  releaseYearMin: string;
  releaseYearMax: string;
  runtimeMinutesMin: string;
  runtimeMinutesMax: string;
  minimumEvidenceCount: string;
  pageSize: string;
};

const defaultFilters: DiscoveryFilters = {
  genres: [],
  originalLanguage: "",
  region: "",
  releaseYearMin: "",
  releaseYearMax: "",
  runtimeMinutesMin: "",
  runtimeMinutesMax: "",
  minimumEvidenceCount: "0",
  pageSize: "20",
};

function parseInteger(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const parsed = Number(trimmed);
  return Number.isInteger(parsed) ? parsed : null;
}

function hasMeaningfulNarrowing(filters: DiscoveryFilters): boolean {
  return Boolean(
    filters.genres.length ||
      filters.originalLanguage.trim() ||
      filters.releaseYearMin.trim() ||
      filters.releaseYearMax.trim() ||
      filters.runtimeMinutesMin.trim() ||
      filters.runtimeMinutesMax.trim() ||
      (parseInteger(filters.minimumEvidenceCount) ?? 0) > 0,
  );
}

function buildManualRequest(filters: DiscoveryFilters, page: number): DiscoveryRequestPayload {
  const request: DiscoveryRequestPayload = {
    media_type: "movie",
    page,
    page_size: parseInteger(filters.pageSize) ?? 20,
  };

  if (filters.genres.length) request.genres = filters.genres;
  if (filters.originalLanguage.trim()) request.original_language = filters.originalLanguage.trim();
  if (filters.region.trim()) request.region = filters.region.trim();

  const releaseYearMin = parseInteger(filters.releaseYearMin);
  if (releaseYearMin !== null) request.release_year_min = releaseYearMin;
  const releaseYearMax = parseInteger(filters.releaseYearMax);
  if (releaseYearMax !== null) request.release_year_max = releaseYearMax;
  const runtimeMinutesMin = parseInteger(filters.runtimeMinutesMin);
  if (runtimeMinutesMin !== null) request.runtime_minutes_min = runtimeMinutesMin;
  const runtimeMinutesMax = parseInteger(filters.runtimeMinutesMax);
  if (runtimeMinutesMax !== null) request.runtime_minutes_max = runtimeMinutesMax;
  const minimumEvidenceCount = parseInteger(filters.minimumEvidenceCount);
  if (minimumEvidenceCount !== null) request.minimum_evidence_count = minimumEvidenceCount;

  return request;
}

function buildStructuredRequestFromNormalized(
  normalized: DiscoveryNormalizedRequest,
  page: number,
): DiscoveryRequestPayload {
  const request: DiscoveryRequestPayload = {
    media_type: "movie",
    page,
    page_size: normalized.page_size,
  };

  if (normalized.genres.length) request.genres = normalized.genres;
  if (normalized.original_language) request.original_language = normalized.original_language;
  if (normalized.region) request.region = normalized.region;
  if (normalized.release_year_min !== null) request.release_year_min = normalized.release_year_min;
  if (normalized.release_year_max !== null) request.release_year_max = normalized.release_year_max;
  if (normalized.runtime_minutes_min !== null) request.runtime_minutes_min = normalized.runtime_minutes_min;
  if (normalized.runtime_minutes_max !== null) request.runtime_minutes_max = normalized.runtime_minutes_max;
  if (normalized.minimum_evidence_count !== 0) request.minimum_evidence_count = normalized.minimum_evidence_count;
  if (normalized.availability_required) request.availability_required = true;

  return request;
}

function activeFilterLabels(request: DiscoveryNormalizedRequest): string[] {
  const labels: string[] = [];

  if (request.genres.length) labels.push(`Genres: ${request.genres.join(", ")}`);
  if (request.original_language) labels.push(`Original language: ${request.original_language}`);
  if (request.region) labels.push(`Region: ${request.region}`);
  if (request.release_year_min !== null || request.release_year_max !== null) {
    labels.push(`Release years: ${request.release_year_min ?? "?"} to ${request.release_year_max ?? "?"}`);
  }
  if (request.runtime_minutes_min !== null || request.runtime_minutes_max !== null) {
    labels.push(`Runtime: ${request.runtime_minutes_min ?? "?"} to ${request.runtime_minutes_max ?? "?"} minutes`);
  }
  if (request.minimum_evidence_count > 0) labels.push(`Minimum evidence count: ${request.minimum_evidence_count}`);
  if (request.availability_required) labels.push("Availability required");
  labels.push(`Page size: ${request.page_size}`);

  return labels;
}

function getManualErrorMessage(statusCode: number, payload: ControlledErrorResponse): string {
  if (statusCode === 422) {
    if (typeof payload.detail === "object" && payload.detail && "error" in payload.detail && payload.detail.error === "unsupported_filter") {
      return "That filter is not available yet. Regional streaming availability is planned for a later phase.";
    }
    if (Array.isArray(payload.detail)) return "Please correct the discovery filters and try again.";
    if (typeof payload.detail === "string" && payload.detail.includes("unrestricted discovery requests")) {
      return "Add at least one narrowing filter before searching.";
    }
    return "Please correct the discovery filters and try again.";
  }
  if (statusCode >= 500) return "The discovery service is temporarily unavailable. Please try again.";
  return "Discovery request failed.";
}

function getDetailErrorCode(payload: ControlledErrorResponse): string | null {
  if (!payload.detail || Array.isArray(payload.detail) || typeof payload.detail !== "object") {
    return null;
  }
  return typeof payload.detail.error === "string" ? payload.detail.error : null;
}

function getNaturalLanguageErrorMessage(statusCode: number, payload: ControlledErrorResponse): string {
  const errorCode = getDetailErrorCode(payload);
  if (statusCode === 422 && errorCode) {
    switch (errorCode) {
      case "unrestricted_interpretation":
        return "Please add at least one specific preference, such as genre, language, year, or runtime.";
      case "invalid_interpretation":
        return "We could not convert that request into valid movie filters. Please try being more specific.";
      case "unsupported_filter":
        return "That filter is not available yet. Regional streaming availability is planned for a later phase.";
    }
  }
  if (statusCode === 503 && errorCode === "interpreter_unavailable") {
    return "Natural-language discovery is temporarily unavailable. You can still use manual filters.";
  }
  if (statusCode === 502 && errorCode === "interpreter_failure") {
    return "We could not interpret that request right now. Please try again or use manual filters.";
  }
  if (statusCode >= 500) {
    return "We could not interpret that request right now. Please try again or use manual filters.";
  }
  return "We could not convert that request into valid movie filters. Please try being more specific.";
}

export function DiscoveryForm() {
  const [mode, setMode] = useState<DiscoveryMode>("natural-language");
  const [filters, setFilters] = useState<DiscoveryFilters>(defaultFilters);
  const [naturalLanguageQuery, setNaturalLanguageQuery] = useState("");
  const [status, setStatus] = useState<DiscoveryStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<DiscoveryResponse | null>(null);
  const [interpretedRequest, setInterpretedRequest] = useState<DiscoveryNormalizedRequest | null>(null);
  const [lastNaturalLanguageQuery, setLastNaturalLanguageQuery] = useState<string | null>(null);
  const [includeShadow, setIncludeShadow] = useState(false);

  const manualCanSubmit = hasMeaningfulNarrowing(filters) && status !== "loading" && status !== "paging";
  const trimmedQuery = naturalLanguageQuery.trim();
  const naturalLanguageCanSubmit =
    trimmedQuery.length > 0 && trimmedQuery.length <= 500 && status !== "loading" && status !== "paging";

  function updateFilter<K extends keyof DiscoveryFilters>(key: K, value: DiscoveryFilters[K]) {
    setFilters((current) => ({ ...current, [key]: value }));
  }

  function toggleGenre(genre: string) {
    setFilters((current) => ({
      ...current,
      genres: current.genres.includes(genre)
        ? current.genres.filter((item) => item !== genre)
        : [...current.genres, genre],
    }));
  }

  function resetResults() {
    setStatus("idle");
    setError(null);
    setResponse(null);
    setInterpretedRequest(null);
    setLastNaturalLanguageQuery(null);
  }

  async function runStructuredDiscovery(request: DiscoveryRequestPayload, nextStatus: "loading" | "paging") {
    setStatus(nextStatus);
    setError(null);

    const result = await fetch(`${apiBase}/api/v1/discover`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...request, include_shadow: includeShadow }),
    });

    const data = (await result.json().catch(() => ({}))) as ControlledErrorResponse | DiscoveryResponse;
    if (!result.ok) {
      setStatus("error");
      setError(getManualErrorMessage(result.status, data as ControlledErrorResponse));
      return;
    }

    const typed = data as DiscoveryResponse;
    setResponse(typed);
    setInterpretedRequest(null);
    setStatus("success");
  }

  async function runNaturalLanguageDiscovery(request: NaturalLanguageDiscoveryRequestPayload) {
    setStatus("loading");
    setError(null);

    const result = await fetch(`${apiBase}/api/v1/discover/natural-language`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...request, include_shadow: includeShadow }),
    });

    const data = (await result.json().catch(() => ({}))) as ControlledErrorResponse | NaturalLanguageDiscoveryResponse;
    if (!result.ok) {
      setStatus("error");
      setError(getNaturalLanguageErrorMessage(result.status, data as ControlledErrorResponse));
      return;
    }

    const typed = data as NaturalLanguageDiscoveryResponse;
    setResponse({
      status: "ok",
      request: typed.interpreted_request,
      results: typed.results,
      page: typed.page,
    });
    setInterpretedRequest(typed.interpreted_request);
    setLastNaturalLanguageQuery(typed.query);
    setStatus("success");
  }

  async function onManualSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!hasMeaningfulNarrowing(filters)) {
      setStatus("error");
      setError("Add at least one narrowing filter before searching.");
      return;
    }
    await runStructuredDiscovery(buildManualRequest(filters, 1), "loading");
  }

  async function onNaturalLanguageSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = naturalLanguageQuery.trim();
    if (!query) {
      setStatus("error");
      setError("Please enter a movie request.");
      return;
    }
    await runNaturalLanguageDiscovery({
      query,
      region: filters.region || undefined,
      page: 1,
      page_size: parseInteger(filters.pageSize) ?? 20,
    });
  }

  async function onPreviousPage() {
    if (!response || response.page.page <= 1 || status === "loading" || status === "paging") return;
    setError(null);
    if (interpretedRequest) {
      await runStructuredDiscovery(buildStructuredRequestFromNormalized(interpretedRequest, response.page.page - 1), "paging");
      return;
    }
    await runStructuredDiscovery(buildStructuredRequestFromNormalized(response.request, response.page.page - 1), "paging");
  }

  async function onNextPage() {
    if (!response || status === "loading" || status === "paging") return;
    if (response.page.returned_count < response.page.requested_page_size) return;
    setError(null);
    if (interpretedRequest) {
      await runStructuredDiscovery(buildStructuredRequestFromNormalized(interpretedRequest, response.page.page + 1), "paging");
      return;
    }
    await runStructuredDiscovery(buildStructuredRequestFromNormalized(response.request, response.page.page + 1), "paging");
  }

  function onManualReset() {
    setFilters(defaultFilters);
    resetResults();
  }

  function onNaturalLanguageClear() {
    setNaturalLanguageQuery("");
    resetResults();
  }

  const summaryRequest = interpretedRequest ?? response?.request ?? null;

  return (
    <section style={styles.shell}>
      <div style={styles.hero}>
        <p style={styles.kicker}>Phase 2E.3</p>
        <h1 style={styles.title}>Discover movies with plain language or manual filters.</h1>
        <p style={styles.copy}>
          Natural-language discovery interprets filters once, then reuses the same structured request for pagination.
          Manual filters still work unchanged and backend ranking stays authoritative.
        </p>
      </div>

      <section style={styles.achievementPanel}>
        <div style={styles.achievementHeader}>
          <p style={styles.kicker}>Discovery Rules</p>
          <p style={styles.achievementCopy}>The LLM only interprets filters. Ranking and validation stay in the backend.</p>
        </div>
        <div style={styles.achievementGrid}>
          <article style={styles.achievementCard}>
            <p style={styles.achievementLabel}>Mode</p>
            <strong style={styles.achievementValue}>Describe or filter manually</strong>
          </article>
          <article style={styles.achievementCard}>
            <p style={styles.achievementLabel}>Pagination</p>
            <strong style={styles.achievementValue}>No repeat LLM call after page 1</strong>
          </article>
          <article style={styles.achievementCard}>
            <p style={styles.achievementLabel}>Availability</p>
            <strong style={styles.achievementValue}>Still planned for Phase 2G</strong>
          </article>
          <article style={styles.achievementCard}>
            <p style={styles.achievementLabel}>Page Size</p>
            <strong style={styles.achievementValue}>Maximum 20 results</strong>
          </article>
        </div>
      </section>

      <section style={styles.modeToggle}>
        <button
          type="button"
          style={mode === "natural-language" ? styles.activeModeButton : styles.modeButton}
          onClick={() => setMode("natural-language")}
        >
          Describe what you want
        </button>
        <button
          type="button"
          style={mode === "manual" ? styles.activeModeButton : styles.modeButton}
          onClick={() => setMode("manual")}
        >
          Manual filters
        </button>
      </section>

      {mode === "natural-language" ? (
        <form onSubmit={onNaturalLanguageSubmit} style={styles.form}>
          <section style={styles.section}>
            <h2 style={styles.subheading}>Describe what you want</h2>
            <label style={styles.field}>
              <span>Movie request</span>
              <textarea
                maxLength={500}
                value={naturalLanguageQuery}
                onChange={(event) => setNaturalLanguageQuery(event.target.value)}
                placeholder="Marathi thrillers released between 2016 and 2018"
                style={styles.textarea}
              />
            </label>
            <p style={styles.helper}>{trimmedQuery.length}/500 characters</p>
            <div style={styles.exampleRow}>
              {examplePrompts.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  style={styles.exampleButton}
                  onClick={() => setNaturalLanguageQuery(prompt)}
                  disabled={status === "loading" || status === "paging"}
                >
                  {prompt}
                </button>
              ))}
            </div>
          </section>

          <section style={styles.section}>
            <h2 style={styles.subheading}>Diagnostics & Page Size</h2>
            <div style={styles.fieldGrid}>
              <label style={styles.field}>
                <span>Results per page</span>
                <input
                  inputMode="numeric"
                  pattern="[0-9]*"
                  value={filters.pageSize}
                  onChange={(event) => updateFilter("pageSize", event.target.value)}
                  style={styles.input}
                />
              </label>
              {showDiagnosticsToggle && (
                <label style={{ ...styles.field, display: "flex", flexDirection: "row", alignItems: "center", gap: 10, cursor: "pointer", minHeight: 48, marginTop: 24 }}>
                  <input
                    id="enable-shadow-diagnostics-nl"
                    type="checkbox"
                    checked={includeShadow}
                    onChange={(event) => setIncludeShadow(event.target.checked)}
                    style={{ width: 20, height: 20, cursor: "pointer" }}
                  />
                  <span style={{ fontWeight: 500, color: "var(--text)" }}>Enable Shadow Diagnostics (v2)</span>
                </label>
              )}
            </div>
          </section>

          <div style={styles.actionRow}>
            <button type="submit" style={styles.button} disabled={!naturalLanguageCanSubmit}>
              {status === "loading" ? "Discovering..." : "Discover movies"}
            </button>
            <button type="button" style={styles.secondaryButton} onClick={onNaturalLanguageClear} disabled={status === "loading" || status === "paging"}>
              Clear
            </button>
          </div>
          {!trimmedQuery ? <p style={styles.helper}>Add a specific preference such as genre, language, year, or runtime.</p> : null}
        </form>
      ) : (
        <form onSubmit={onManualSubmit} style={styles.form}>
          <section style={styles.section}>
            <h2 style={styles.subheading}>Genres</h2>
            <div style={styles.genreGrid}>
              {genreOptions.map(([slug, label]) => (
                <label key={slug} style={styles.genreChip}>
                  <input type="checkbox" checked={filters.genres.includes(slug)} onChange={() => toggleGenre(slug)} />
                  <span>{label}</span>
                </label>
              ))}
            </div>
          </section>

          <section style={styles.section}>
            <h2 style={styles.subheading}>Structured Filters</h2>
            <div style={styles.fieldGrid}>
              <label style={styles.field}>
                <span>Original language</span>
                <input maxLength={2} value={filters.originalLanguage} onChange={(event) => updateFilter("originalLanguage", event.target.value.toLowerCase())} style={styles.input} />
              </label>
              <label style={styles.field}>
                <span>Region</span>
                <input maxLength={2} value={filters.region} onChange={(event) => updateFilter("region", event.target.value.toUpperCase())} style={styles.input} />
              </label>
              <label style={styles.field}>
                <span>Release year min</span>
                <input inputMode="numeric" pattern="[0-9]*" value={filters.releaseYearMin} onChange={(event) => updateFilter("releaseYearMin", event.target.value)} style={styles.input} />
              </label>
              <label style={styles.field}>
                <span>Release year max</span>
                <input inputMode="numeric" pattern="[0-9]*" value={filters.releaseYearMax} onChange={(event) => updateFilter("releaseYearMax", event.target.value)} style={styles.input} />
              </label>
              <label style={styles.field}>
                <span>Runtime min</span>
                <input inputMode="numeric" pattern="[0-9]*" value={filters.runtimeMinutesMin} onChange={(event) => updateFilter("runtimeMinutesMin", event.target.value)} style={styles.input} />
              </label>
              <label style={styles.field}>
                <span>Runtime max</span>
                <input inputMode="numeric" pattern="[0-9]*" value={filters.runtimeMinutesMax} onChange={(event) => updateFilter("runtimeMinutesMax", event.target.value)} style={styles.input} />
              </label>
              <label style={styles.field}>
                <span>Minimum evidence count</span>
                <input inputMode="numeric" pattern="[0-9]*" value={filters.minimumEvidenceCount} onChange={(event) => updateFilter("minimumEvidenceCount", event.target.value)} style={styles.input} />
              </label>
              <label style={styles.field}>
                <span>Page size</span>
                <input inputMode="numeric" pattern="[0-9]*" value={filters.pageSize} onChange={(event) => updateFilter("pageSize", event.target.value)} style={styles.input} />
              </label>
            </div>
          </section>

          <section style={styles.section}>
            <h2 style={styles.subheading}>Availability & Diagnostics</h2>
            <div style={{ display: "grid", gap: 12 }}>
              <label style={styles.disabledField}>
                <input type="checkbox" disabled />
                <span>Regional streaming availability (coming later)</span>
              </label>
              {showDiagnosticsToggle && (
                <label style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 10, cursor: "pointer" }}>
                  <input
                    id="enable-shadow-diagnostics-manual"
                    type="checkbox"
                    checked={includeShadow}
                    onChange={(event) => setIncludeShadow(event.target.checked)}
                    style={{ width: 18, height: 18, cursor: "pointer" }}
                  />
                  <span style={{ fontWeight: 500, color: "var(--text)" }}>Enable Shadow Diagnostics (v2)</span>
                </label>
              )}
            </div>
            <p style={styles.helper}>Streaming availability stays disabled. Shadow diagnostics shows local v2 comparison data.</p>
          </section>

          <div style={styles.actionRow}>
            <button type="submit" style={styles.button} disabled={!manualCanSubmit}>
              {status === "loading" ? "Discovering..." : "Discover movies"}
            </button>
            <button type="button" style={styles.secondaryButton} onClick={onManualReset} disabled={status === "loading" || status === "paging"}>
              Reset filters
            </button>
          </div>
          {!hasMeaningfulNarrowing(filters) ? (
            <p style={styles.helper}>Add a genre, language, year bound, runtime bound, or minimum evidence count above zero before searching.</p>
          ) : null}
        </form>
      )}

      {error ? <p style={styles.error}>{error}</p> : null}

      <DiscoveryResultsPanel
        response={response}
        status={status}
        mode={mode}
        interpretedRequest={summaryRequest}
        naturalLanguageQuery={lastNaturalLanguageQuery}
        onNextPage={onNextPage}
        onPreviousPage={onPreviousPage}
      />
    </section>
  );
}

function DiscoveryResultsPanel({
  response,
  status,
  mode,
  interpretedRequest,
  naturalLanguageQuery,
  onNextPage,
  onPreviousPage,
}: {
  response: DiscoveryResponse | null;
  status: DiscoveryStatus;
  mode: DiscoveryMode;
  interpretedRequest: DiscoveryNormalizedRequest | null;
  naturalLanguageQuery: string | null;
  onNextPage: () => void;
  onPreviousPage: () => void;
}) {
  if (status === "idle") {
    return (
      <section style={styles.card}>
        <div style={styles.headline}>
          <div>
            <p style={styles.eyebrow}>Discovery</p>
            <h2 style={styles.resultTitle}>Ready for a movie search</h2>
          </div>
        </div>
        <p style={styles.overview}>
          {mode === "natural-language"
            ? "Describe the kind of movie you want, then let the backend validate and rank the results."
            : "Choose at least one narrowing filter, then submit a provider-neutral discovery request."}
        </p>
      </section>
    );
  }

  if (status === "loading" || status === "paging") {
    return (
      <section style={styles.card}>
        <div style={styles.headline}>
          <div>
            <p style={styles.eyebrow}>Discovery</p>
            <h2 style={styles.resultTitle}>{status === "loading" ? "Preparing ranked results…" : "Loading another page…"}</h2>
          </div>
        </div>
        <p style={styles.overview}>
          {status === "loading"
            ? "Waiting for the backend to validate the request and return ranked matches."
            : "Reusing the stored structured filters and fetching the next ranked page."}
        </p>
      </section>
    );
  }

  if (!response || response.results.length === 0) {
    return (
      <section style={styles.card}>
        <div style={styles.headline}>
          <div>
            <p style={styles.eyebrow}>Discovery</p>
            <h2 style={styles.resultTitle}>No movies matched this search</h2>
          </div>
        </div>
        <p style={styles.overview}>Try broadening the filters or reducing the minimum evidence count.</p>
      </section>
    );
  }

  const nextDisabled = response.page.returned_count < response.page.requested_page_size;
  const previousDisabled = response.page.page <= 1;

  return (
    <section style={styles.card}>
      <div style={styles.headline}>
        <div>
          <p style={styles.eyebrow}>Discovery</p>
          <h2 style={styles.resultTitle}>Ranked movies from the structured pipeline</h2>
          <p style={styles.meta}>
            page {response.page.page} · requested {response.page.requested_page_size} · returned {response.page.returned_count}
          </p>
        </div>
      </div>

      {naturalLanguageQuery ? (
        <article style={styles.panel}>
          <h3 style={styles.sectionTitle}>Original request</h3>
          <p style={styles.small}>{naturalLanguageQuery}</p>
        </article>
      ) : null}

      {interpretedRequest ? (
        <article style={styles.panel}>
          <h3 style={styles.sectionTitle}>{naturalLanguageQuery ? "Interpreted filters" : "Normalized request"}</h3>
          <div style={styles.filterList}>
            {activeFilterLabels(interpretedRequest).map((label) => (
              <span key={label} style={styles.filterBadge}>
                {label}
              </span>
            ))}
          </div>
        </article>
      ) : null}

      <div style={styles.paginationRow}>
        <button type="button" style={styles.secondaryButton} onClick={onPreviousPage} disabled={previousDisabled}>
          Previous
        </button>
        <button type="button" style={styles.secondaryButton} onClick={onNextPage} disabled={nextDisabled}>
          Next
        </button>
      </div>

      <div style={styles.recommendationList}>
        {response.results.slice(0, 20).map((item) => (
          <article key={`${item.tmdb_source_movie_id}-${item.movie.movie_id}`} style={styles.recommendationCard}>
            <div style={styles.recommendationHeader}>
              {item.movie.poster_url ? (
                <img src={item.movie.poster_url} alt={`${item.movie.canonical_title} poster`} style={styles.poster} />
              ) : (
                <div style={styles.posterFallback}>No poster</div>
              )}
              <div style={styles.recommendationIntro}>
                <p style={styles.eyebrow}>Provider position {item.provider_position + 1}</p>
                <h3 style={styles.recommendationTitle}>
                  {item.movie.canonical_title} {item.movie.release_year ? `(${item.movie.release_year})` : ""}
                </h3>
                <p style={styles.meta}>
                  {item.movie.original_language ?? "unknown language"} · {item.score_version} · {item.score.toFixed(2)}
                </p>
              </div>
            </div>

            <p style={styles.overview}>{item.movie.overview || "No overview was returned."}</p>

            <div style={styles.grid}>
              <article style={styles.panel}>
                <h4 style={styles.sectionTitle}>Score Breakdown</h4>
                <ul style={styles.list}>
                  {Object.entries(item.score_components).map(([key, value]) => (
                    <li key={key} style={styles.item}>
                      <span>{key}</span>
                      <strong>{value === null ? "missing" : value.toFixed(2)}</strong>
                    </li>
                  ))}
                </ul>
              </article>

              <article style={styles.panel}>
                <h4 style={styles.sectionTitle}>Freshness</h4>
                <ul style={styles.list}>
                  {Object.entries(item.freshness).map(([key, value]) => (
                    <li key={key} style={styles.item}>
                      <span>{key}</span>
                      <strong>{value}</strong>
                    </li>
                  ))}
                </ul>
              </article>
            </div>

            <div style={styles.grid}>
              <article style={styles.panel}>
                <h4 style={styles.sectionTitle}>Missing Signals</h4>
                <p style={styles.small}>{item.missing_signals.length ? item.missing_signals.join(", ") : "None"}</p>
              </article>

              <article style={styles.panel}>
                <h4 style={styles.sectionTitle}>Provenance</h4>
                <p style={styles.small}>Source: {item.provenance.source}</p>
                <p style={styles.small}>TMDB ID: {item.tmdb_source_movie_id}</p>
                <p style={styles.small}>
                  Source URL:{" "}
                  {item.provenance.source_url ? (
                    <a href={item.provenance.source_url} target="_blank" rel="noreferrer">
                      {item.provenance.source_url}
                    </a>
                  ) : (
                    "unavailable"
                  )}
                </p>
              </article>
            </div>

            {item.shadow_comparison && (
              <div style={{ ...styles.grid, marginTop: 12 }}>
                <article style={{ ...styles.panel, gridColumn: "span 2", border: "1px dashed var(--accent)", background: "rgba(141,46,22,0.03)" }}>
                  <h4 style={{ ...styles.sectionTitle, color: "var(--accent)" }}>Shadow Diagnostics (cine-score-v2)</h4>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12, marginTop: 8 }}>
                    <div>
                      <p style={{ margin: "2px 0", fontSize: 12 }}><strong>Shadow Version:</strong> {item.shadow_comparison.score_version}</p>
                      <p style={{ margin: "2px 0", fontSize: 12 }}>
                        <strong>V2 Score:</strong> {item.shadow_comparison.v2_score !== null ? item.shadow_comparison.v2_score.toFixed(2) : "N/A"}
                      </p>
                      <p style={{ margin: "2px 0", fontSize: 12 }}>
                        <strong>V2 Rank:</strong> {item.shadow_comparison.v2_rank !== null ? `#${item.shadow_comparison.v2_rank}` : "N/A"} (V1: #{item.shadow_comparison.v1_rank})
                      </p>
                      <p style={{ margin: "2px 0", fontSize: 12 }}>
                        <strong>Movement:</strong> {item.shadow_comparison.rank_movement !== null ? (item.shadow_comparison.rank_movement > 0 ? `+${item.shadow_comparison.rank_movement}` : item.shadow_comparison.rank_movement) : "N/A"}
                      </p>
                    </div>
                    <div>
                      <p style={{ margin: "2px 0", fontSize: 12 }}><strong>Evidence Gate:</strong> {item.shadow_comparison.evidence_gate || "N/A"}</p>
                      <p style={{ margin: "2px 0", fontSize: 12 }}><strong>Human Review:</strong> {item.shadow_comparison.review_status || "PENDING"}</p>
                      <p style={{ margin: "2px 0", fontSize: 12 }}><strong>Activation Eligible:</strong> {item.shadow_comparison.activation_eligible ? "Yes" : "No"}</p>
                      {item.shadow_comparison.ineligible_reason && (
                        <p style={{ margin: "2px 0", fontSize: 12, color: "var(--accent)" }}><strong>Ineligible:</strong> {item.shadow_comparison.ineligible_reason}</p>
                      )}
                    </div>
                  </div>
                </article>
              </div>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

const styles: Record<string, CSSProperties> = {
  shell: { maxWidth: 980, margin: "0 auto", display: "grid", gap: 24 },
  hero: { padding: "32px 32px 12px" },
  kicker: { margin: 0, color: "var(--accent)", letterSpacing: "0.16em", textTransform: "uppercase", fontSize: 12 },
  title: { margin: "10px 0 12px", fontSize: "clamp(2.2rem, 5vw, 4rem)" },
  copy: { margin: 0, maxWidth: 700, color: "var(--muted)", lineHeight: 1.7 },
  achievementPanel: { display: "grid", gap: 18, padding: "0 32px" },
  achievementHeader: { display: "flex", justifyContent: "space-between", gap: 16, alignItems: "end", flexWrap: "wrap" },
  achievementCopy: { margin: 0, color: "var(--muted)" },
  achievementGrid: { display: "grid", gap: 14, gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" },
  achievementCard: {
    borderRadius: 22,
    padding: "18px 20px",
    background: "linear-gradient(180deg, rgba(255,255,255,0.82) 0%, rgba(248,232,213,0.92) 100%)",
    border: "1px solid rgba(141,46,22,0.14)",
    boxShadow: "0 18px 40px rgba(86, 42, 16, 0.08)",
  },
  achievementLabel: { margin: 0, color: "var(--accent)", textTransform: "uppercase", letterSpacing: "0.12em", fontSize: 11 },
  achievementValue: { display: "block", marginTop: 8, fontSize: "clamp(1rem, 2vw, 1.25rem)" },
  modeToggle: { display: "flex", gap: 12, padding: "0 32px", flexWrap: "wrap" },
  modeButton: {
    minHeight: 44,
    borderRadius: 999,
    border: "1px solid var(--line)",
    background: "rgba(255,255,255,0.7)",
    color: "var(--text)",
    padding: "0 18px",
    cursor: "pointer",
  },
  activeModeButton: {
    minHeight: 44,
    borderRadius: 999,
    border: "1px solid rgba(141,46,22,0.2)",
    background: "linear-gradient(135deg, rgba(141,46,22,0.16) 0%, rgba(200,95,51,0.16) 100%)",
    color: "var(--text)",
    padding: "0 18px",
    cursor: "pointer",
  },
  form: { display: "grid", gap: 20, borderRadius: 28, background: "var(--panel)", boxShadow: "var(--shadow)", padding: 32 },
  section: { display: "grid", gap: 14 },
  subheading: { margin: 0, fontSize: "clamp(1.2rem, 2vw, 1.5rem)" },
  genreGrid: { display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" },
  genreChip: { display: "flex", alignItems: "center", gap: 10, padding: "12px 14px", borderRadius: 18, background: "rgba(255,255,255,0.58)", border: "1px solid var(--line)" },
  fieldGrid: { display: "grid", gap: 16, gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" },
  field: { display: "grid", gap: 8 },
  input: { minHeight: 48, borderRadius: 16, border: "1px solid var(--line)", padding: "0 14px", background: "rgba(255,255,255,0.78)" },
  textarea: {
    minHeight: 128,
    borderRadius: 16,
    border: "1px solid var(--line)",
    padding: "14px",
    background: "rgba(255,255,255,0.78)",
    resize: "vertical",
    font: "inherit",
  },
  exampleRow: { display: "flex", gap: 10, flexWrap: "wrap" },
  exampleButton: {
    borderRadius: 999,
    border: "1px solid var(--line)",
    background: "rgba(255,255,255,0.7)",
    color: "var(--text)",
    padding: "10px 14px",
    cursor: "pointer",
    textAlign: "left",
  },
  disabledField: { display: "flex", gap: 10, alignItems: "center", color: "var(--muted)" },
  helper: { margin: 0, color: "var(--muted)", lineHeight: 1.6 },
  actionRow: { display: "flex", gap: 12, flexWrap: "wrap" },
  button: {
    minHeight: 48,
    borderRadius: 999,
    border: 0,
    background: "linear-gradient(135deg, #8d2e16 0%, #c85f33 100%)",
    color: "#fff8f0",
    padding: "0 24px",
    cursor: "pointer",
  },
  secondaryButton: {
    minHeight: 48,
    borderRadius: 999,
    border: "1px solid var(--line)",
    background: "rgba(255,255,255,0.7)",
    color: "var(--text)",
    padding: "0 24px",
    cursor: "pointer",
  },
  error: {
    margin: 0,
    color: "#8d2e16",
    background: "rgba(200,95,51,0.08)",
    border: "1px solid rgba(141,46,22,0.18)",
    borderRadius: 18,
    padding: "14px 18px",
  },
  card: { display: "grid", gap: 20, borderRadius: 28, background: "var(--panel)", boxShadow: "var(--shadow)", padding: 32 },
  headline: { display: "flex", justifyContent: "space-between", gap: 16, alignItems: "start", flexWrap: "wrap" },
  eyebrow: { margin: 0, color: "var(--accent)", textTransform: "uppercase", letterSpacing: "0.16em", fontSize: 12 },
  resultTitle: { margin: "8px 0", fontSize: "clamp(2rem, 4vw, 3rem)" },
  meta: { margin: 0, color: "var(--muted)" },
  overview: { margin: 0, lineHeight: 1.6, color: "var(--muted)" },
  filterList: { display: "flex", gap: 10, flexWrap: "wrap" },
  filterBadge: {
    borderRadius: 999,
    border: "1px solid var(--line)",
    background: "rgba(255,255,255,0.75)",
    padding: "8px 12px",
    color: "var(--text)",
  },
  paginationRow: { display: "flex", gap: 12, flexWrap: "wrap" },
  recommendationList: { display: "grid", gap: 20 },
  recommendationCard: { display: "grid", gap: 16, borderRadius: 24, padding: 24, background: "rgba(255,255,255,0.58)", border: "1px solid var(--line)" },
  recommendationHeader: { display: "grid", gridTemplateColumns: "88px minmax(0, 1fr)", gap: 16, alignItems: "start" },
  poster: { width: 88, height: 132, objectFit: "cover", borderRadius: 16, background: "rgba(255,255,255,0.8)", border: "1px solid var(--line)" },
  posterFallback: {
    width: 88,
    height: 132,
    borderRadius: 16,
    border: "1px dashed var(--line)",
    background: "rgba(255,255,255,0.35)",
    display: "grid",
    placeItems: "center",
    color: "var(--muted)",
    fontSize: 12,
    textAlign: "center",
    padding: 8,
  },
  recommendationIntro: { minWidth: 0 },
  recommendationTitle: { margin: "6px 0 8px", fontSize: "clamp(1.5rem, 3vw, 2rem)" },
  grid: { display: "grid", gap: 16, gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" },
  panel: { border: "1px solid var(--line)", borderRadius: 20, padding: 20, background: "rgba(255,255,255,0.55)" },
  sectionTitle: { marginTop: 0, marginBottom: 12 },
  list: { listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 10 },
  item: { display: "flex", justifyContent: "space-between", gap: 12 },
  small: { margin: "6px 0", color: "var(--muted)", lineHeight: 1.5 },
};
