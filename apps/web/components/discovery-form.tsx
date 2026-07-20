"use client";

import type { CSSProperties, FormEvent } from "react";
import { useState, useEffect } from "react";

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

  useEffect(() => {
    if (typeof window !== "undefined") {
      const searchParams = new URLSearchParams(window.location.search);
      const q = searchParams.get("q");
      if (q && !naturalLanguageQuery && status === "idle") {
        setNaturalLanguageQuery(q);
        setMode("natural-language");
        runNaturalLanguageDiscovery({
          query: q,
          region: filters.region || undefined,
          page: 1,
          page_size: parseInteger(filters.pageSize) ?? 20,
        });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

        <h1 style={styles.title}>Discover movies with plain language or manual filters.</h1>
        <p style={styles.copy}>
          Natural-language discovery interprets filters once, then reuses the same structured request for pagination.
          Manual filters still work unchanged and backend ranking stays authoritative.
        </p>
      </div>



      <section style={styles.modeToggle}>
        <button
          type="button"
          className="interactive"
          style={mode === "natural-language" ? styles.activeModeButton : styles.modeButton}
          onClick={() => setMode("natural-language")}
        >
          Describe what you want
        </button>
        <button
          type="button"
          className="interactive"
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
                  className="interactive"
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
            <button type="submit" className="interactive" style={styles.button} disabled={!naturalLanguageCanSubmit}>
              {status === "loading" ? "Searching…" : "Discover"}
            </button>
            <button type="button" className="interactive" style={styles.secondaryButton} onClick={onNaturalLanguageClear} disabled={status === "loading" || status === "paging"}>
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
            <button type="submit" className="interactive" style={styles.button} disabled={!manualCanSubmit}>
              {status === "loading" ? "Searching…" : "Discover"}
            </button>
            <button type="button" className="interactive" style={styles.secondaryButton} onClick={onManualReset} disabled={status === "loading" || status === "paging"}>
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
        <button type="button" className="interactive" style={styles.secondaryButton} onClick={onPreviousPage} disabled={previousDisabled}>
          Previous
        </button>
        <button type="button" className="interactive" style={styles.secondaryButton} onClick={onNextPage} disabled={nextDisabled}>
          Next
        </button>
      </div>

      <div style={styles.recommendationList}>
        {response.results.slice(0, 20).map((item) => (
          <article key={`${item.tmdb_source_movie_id}-${item.movie.movie_id}`} className="interactive" style={styles.posterCard}>
            <div style={styles.posterWrapper}>
              {item.movie.poster_url ? (
                <img
                  src={item.movie.poster_url}
                  alt={`${item.movie.canonical_title} poster`}
                  style={styles.cardPoster}
                />
              ) : (
                <div style={styles.cardPosterFallback}>No poster</div>
              )}
              <div style={styles.cardOverlay}>
                <span style={styles.cardScore}>{item.score.toFixed(1)}</span>
              </div>
            </div>

            <div style={styles.cardInfo}>
              <h3 style={styles.cardTitle}>{item.movie.canonical_title}</h3>
              <p style={styles.cardMeta}>
                {item.movie.release_year || "YYYY"} • {item.movie.original_language?.toUpperCase() || "UN"}
              </p>

              <div style={styles.cardHoverActions}>
                <span title={`Version ${item.score_version}`} style={styles.tooltipIcon}>ℹ️</span>
                <button type="button" className="interactive" style={styles.textAction}>View details</button>
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

const styles: Record<string, CSSProperties> = {
  shell: { maxWidth: 1024, margin: "0 auto", display: "flex", flexDirection: "column", gap: 32, padding: "40px 0" },
  hero: { textAlign: "center", padding: "32px 20px 24px", display: "flex", flexDirection: "column", alignItems: "center" },
  title: { margin: "0 0 16px", fontSize: "clamp(2.5rem, 6vw, 4rem)", fontWeight: 800, letterSpacing: "-0.03em" },
  copy: { margin: "0 0 24px", fontSize: "clamp(1.1rem, 2vw, 1.4rem)", color: "var(--muted)", maxWidth: 600 },
  modeToggle: { display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap", marginBottom: 16 },
  modeButton: { minHeight: 44, borderRadius: 999, border: "1px solid var(--line)", background: "var(--surface)", color: "var(--text)", padding: "0 24px", cursor: "pointer", fontWeight: 600 },
  activeModeButton: { minHeight: 44, borderRadius: 999, border: "none", background: "var(--accent)", color: "#fff", padding: "0 24px", cursor: "pointer", fontWeight: 600 },
  form: { display: "flex", flexDirection: "column", gap: 24, padding: 32, borderRadius: 24, background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow)", backdropFilter: "blur(20px)" },
  section: { display: "flex", flexDirection: "column", gap: 16 },
  subheading: { margin: 0, fontSize: 20, fontWeight: 600 },
  genreGrid: { display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" },
  genreChip: { display: "flex", alignItems: "center", gap: 10, padding: "12px 14px", borderRadius: 12, background: "var(--surface-elevated)", border: "1px solid var(--line)", cursor: "pointer" },
  fieldGrid: { display: "grid", gap: 16, gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" },
  field: { display: "flex", flexDirection: "column", gap: 8, fontSize: 14, color: "var(--muted)" },
  input: { minHeight: 48, borderRadius: 12, border: "1px solid var(--line)", padding: "0 16px", background: "var(--surface-elevated)", color: "var(--text)" },
  textarea: { minHeight: 120, borderRadius: 12, border: "1px solid var(--line)", padding: "16px", background: "var(--surface-elevated)", color: "var(--text)", resize: "vertical", fontSize: "1.1rem" },
  exampleRow: { display: "flex", gap: 10, flexWrap: "wrap", marginTop: 8 },
  exampleButton: { borderRadius: 999, border: "1px solid var(--line)", background: "var(--surface)", color: "var(--text)", padding: "8px 16px", cursor: "pointer", fontSize: 13 },
  disabledField: { display: "flex", gap: 10, alignItems: "center", color: "var(--muted)" },
  helper: { margin: 0, color: "var(--muted)", fontSize: 14 },
  actionRow: { display: "flex", gap: 12, flexWrap: "wrap", marginTop: 8 },
  button: { minHeight: 48, borderRadius: 999, border: "none", background: "var(--accent)", color: "#fff", padding: "0 32px", fontWeight: 600, cursor: "pointer" },
  secondaryButton: { minHeight: 48, borderRadius: 999, border: "1px solid var(--line)", background: "transparent", color: "var(--text)", padding: "0 24px", cursor: "pointer" },
  error: { margin: 0, color: "var(--error-text)", background: "var(--error-bg)", border: "1px solid var(--error-border)", borderRadius: 12, padding: "16px 20px" },
  card: { display: "flex", flexDirection: "column", gap: 20, borderRadius: 24, background: "var(--panel)", boxShadow: "var(--shadow)", padding: 32, border: "1px solid var(--line)" },
  headline: { display: "flex", justifyContent: "space-between", gap: 16, alignItems: "start", flexWrap: "wrap" },
  eyebrow: { margin: 0, color: "var(--accent)", textTransform: "uppercase", letterSpacing: "0.16em", fontSize: 12 },
  resultTitle: { margin: "8px 0", fontSize: "clamp(1.5rem, 3vw, 2.5rem)", fontWeight: 700 },
  meta: { margin: 0, color: "var(--muted)", fontSize: 14 },
  overview: { margin: 0, lineHeight: 1.6, color: "var(--text)" },
  filterList: { display: "flex", gap: 10, flexWrap: "wrap" },
  filterBadge: { borderRadius: 999, border: "1px solid var(--line)", background: "var(--surface)", padding: "8px 12px", color: "var(--text)", fontSize: 13 },
  paginationRow: { display: "flex", gap: 12, flexWrap: "wrap" },
  recommendationList: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 20 },
  posterCard: { display: "flex", flexDirection: "column", gap: 12, cursor: "pointer" },
  posterWrapper: { position: "relative", aspectRatio: "2/3", borderRadius: 16, overflow: "hidden", boxShadow: "var(--shadow)", backgroundColor: "var(--surface)" },
  cardPoster: { width: "100%", height: "100%", objectFit: "cover" },
  cardPosterFallback: { width: "100%", height: "100%", background: "var(--surface)", display: "grid", placeItems: "center", color: "var(--muted)", fontSize: 12, border: "1px dashed var(--line)" },
  cardOverlay: { position: "absolute", top: 8, right: 8, background: "var(--panel)", borderRadius: 8, padding: "4px 8px", display: "flex", alignItems: "center", boxShadow: "var(--shadow)" },
  cardScore: { color: "var(--accent)", fontWeight: 700, fontSize: 13 },
  cardInfo: { display: "flex", flexDirection: "column", gap: 4 },
  cardTitle: { margin: 0, fontSize: 15, fontWeight: 600, lineHeight: 1.2, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" },
  cardMeta: { margin: 0, fontSize: 13, color: "var(--muted)" },
  cardHoverActions: { display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 4 },
  tooltipIcon: { cursor: "help", fontSize: 12, opacity: 0.5 },
  textAction: { background: "none", border: "none", color: "var(--accent)", fontSize: 13, fontWeight: 600, cursor: "pointer", padding: 0 },
  panel: { border: "1px solid var(--line)", borderRadius: 16, padding: 16, background: "var(--surface)" },
  sectionTitle: { marginTop: 0, marginBottom: 12, fontSize: 16 },
  small: { margin: "4px 0", color: "var(--text)", fontSize: 14 },
};
