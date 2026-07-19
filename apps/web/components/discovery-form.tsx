"use client";

import type { CSSProperties, FormEvent } from "react";
import { useState } from "react";

import type { DiscoveryRequestPayload, DiscoveryResponse } from "@/lib/types";

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

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

type DiscoveryStatus = "idle" | "loading" | "error" | "success";

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
      parseInteger(filters.minimumEvidenceCount) !== null && parseInteger(filters.minimumEvidenceCount)! > 0
  );
}

function buildRequest(filters: DiscoveryFilters, page: number): DiscoveryRequestPayload {
  const request: DiscoveryRequestPayload = {
    media_type: "movie",
    page,
    page_size: parseInteger(filters.pageSize) ?? 20,
  };

  if (filters.genres.length) {
    request.genres = filters.genres;
  }
  if (filters.originalLanguage.trim()) {
    request.original_language = filters.originalLanguage.trim();
  }
  if (filters.region.trim()) {
    request.region = filters.region.trim();
  }
  const releaseYearMin = parseInteger(filters.releaseYearMin);
  if (releaseYearMin !== null) {
    request.release_year_min = releaseYearMin;
  }
  const releaseYearMax = parseInteger(filters.releaseYearMax);
  if (releaseYearMax !== null) {
    request.release_year_max = releaseYearMax;
  }
  const runtimeMinutesMin = parseInteger(filters.runtimeMinutesMin);
  if (runtimeMinutesMin !== null) {
    request.runtime_minutes_min = runtimeMinutesMin;
  }
  const runtimeMinutesMax = parseInteger(filters.runtimeMinutesMax);
  if (runtimeMinutesMax !== null) {
    request.runtime_minutes_max = runtimeMinutesMax;
  }
  const minimumEvidenceCount = parseInteger(filters.minimumEvidenceCount);
  if (minimumEvidenceCount !== null) {
    request.minimum_evidence_count = minimumEvidenceCount;
  }

  return request;
}

function buildRequestFromNormalized(normalized: DiscoveryResponse["request"], page: number): DiscoveryRequestPayload {
  const request: DiscoveryRequestPayload = {
    media_type: "movie",
    page,
    page_size: normalized.page_size,
  };

  if (normalized.genres.length) {
    request.genres = normalized.genres;
  }
  if (normalized.original_language) {
    request.original_language = normalized.original_language;
  }
  if (normalized.region) {
    request.region = normalized.region;
  }
  if (normalized.release_year_min !== null) {
    request.release_year_min = normalized.release_year_min;
  }
  if (normalized.release_year_max !== null) {
    request.release_year_max = normalized.release_year_max;
  }
  if (normalized.runtime_minutes_min !== null) {
    request.runtime_minutes_min = normalized.runtime_minutes_min;
  }
  if (normalized.runtime_minutes_max !== null) {
    request.runtime_minutes_max = normalized.runtime_minutes_max;
  }
  if (normalized.minimum_evidence_count !== 0) {
    request.minimum_evidence_count = normalized.minimum_evidence_count;
  }

  return request;
}

function getErrorMessage(statusCode: number, payload: unknown): string {
  if (statusCode === 422) {
    if (
      typeof payload === "object" &&
      payload !== null &&
      "detail" in payload &&
      typeof (payload as { detail?: unknown }).detail === "object" &&
      (payload as { detail?: { error?: string } }).detail?.error === "unsupported_filter"
    ) {
      return "Availability filtering is planned for Phase 2G and is not enabled yet.";
    }

    const detail = typeof payload === "object" && payload !== null ? (payload as { detail?: unknown }).detail : null;
    if (Array.isArray(detail)) {
      return "Please correct the discovery filters and try again.";
    }
    if (typeof detail === "string" && detail.includes("unrestricted discovery requests")) {
      return "Add at least one narrowing filter before searching.";
    }
    return "Please correct the discovery filters and try again.";
  }

  if (statusCode >= 500) {
    return "The discovery service is temporarily unavailable. Please try again.";
  }

  return "Discovery request failed.";
}

export function DiscoveryForm() {
  const [filters, setFilters] = useState<DiscoveryFilters>(defaultFilters);
  const [status, setStatus] = useState<DiscoveryStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<DiscoveryResponse | null>(null);

  const canSubmit = hasMeaningfulNarrowing(filters) && status !== "loading";

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

  async function runDiscovery(request: DiscoveryRequestPayload) {
    setStatus("loading");
    setError(null);

    const requestResult = await fetch(`${apiBase}/api/v1/discover`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });

    const data = await requestResult.json().catch(() => ({}));
    if (!requestResult.ok) {
      setStatus("error");
      setError(getErrorMessage(requestResult.status, data));
      return;
    }

    setResponse(data as DiscoveryResponse);
    setStatus("success");
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!hasMeaningfulNarrowing(filters)) {
      setStatus("error");
      setError("Add at least one narrowing filter before searching.");
      return;
    }
    await runDiscovery(buildRequest(filters, 1));
  }

  async function onPreviousPage() {
    if (!response || response.page.page <= 1 || status === "loading") {
      return;
    }
    await runDiscovery(buildRequestFromNormalized(response.request, response.page.page - 1));
  }

  async function onNextPage() {
    if (!response || status === "loading") {
      return;
    }
    if (response.page.returned_count < response.page.requested_page_size) {
      return;
    }
    await runDiscovery(buildRequestFromNormalized(response.request, response.page.page + 1));
  }

  function onReset() {
    setFilters(defaultFilters);
    setStatus("idle");
    setError(null);
    setResponse(null);
  }

  return (
    <section style={styles.shell}>
      <div style={styles.hero}>
        <p style={styles.kicker}>Phase 2D.2</p>
        <h1 style={styles.title}>Structured movie discovery, manual filters only.</h1>
        <p style={styles.copy}>
          Build a provider-neutral request from explicit filters, keep backend ranking authoritative,
          and inspect score breakdown, provenance, freshness, and missing signals without free-text shortcuts.
        </p>
      </div>

      <section style={styles.achievementPanel}>
        <div style={styles.achievementHeader}>
          <p style={styles.kicker}>Discovery Rules</p>
          <p style={styles.achievementCopy}>Region alone does not count as narrowing, and availability stays off until Phase 2G.</p>
        </div>
        <div style={styles.achievementGrid}>
          <article style={styles.achievementCard}>
            <p style={styles.achievementLabel}>Contract</p>
            <strong style={styles.achievementValue}>Phase 2A structured request only</strong>
          </article>
          <article style={styles.achievementCard}>
            <p style={styles.achievementLabel}>Ranking</p>
            <strong style={styles.achievementValue}>Backend order preserved</strong>
          </article>
          <article style={styles.achievementCard}>
            <p style={styles.achievementLabel}>Availability</p>
            <strong style={styles.achievementValue}>Coming in Phase 2G</strong>
          </article>
          <article style={styles.achievementCard}>
            <p style={styles.achievementLabel}>Page Size</p>
            <strong style={styles.achievementValue}>Maximum 20 results</strong>
          </article>
        </div>
      </section>

      <form onSubmit={onSubmit} style={styles.form}>
        <section style={styles.section}>
          <h2 style={styles.subheading}>Genres</h2>
          <div style={styles.genreGrid}>
            {genreOptions.map(([slug, label]) => (
              <label key={slug} style={styles.genreChip}>
                <input
                  type="checkbox"
                  checked={filters.genres.includes(slug)}
                  onChange={() => toggleGenre(slug)}
                />
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
              <input
                maxLength={2}
                value={filters.originalLanguage}
                onChange={(event) => updateFilter("originalLanguage", event.target.value.toLowerCase())}
                style={styles.input}
              />
            </label>
            <label style={styles.field}>
              <span>Region</span>
              <input
                maxLength={2}
                value={filters.region}
                onChange={(event) => updateFilter("region", event.target.value.toUpperCase())}
                style={styles.input}
              />
            </label>
            <label style={styles.field}>
              <span>Release year min</span>
              <input
                inputMode="numeric"
                pattern="[0-9]*"
                value={filters.releaseYearMin}
                onChange={(event) => updateFilter("releaseYearMin", event.target.value)}
                style={styles.input}
              />
            </label>
            <label style={styles.field}>
              <span>Release year max</span>
              <input
                inputMode="numeric"
                pattern="[0-9]*"
                value={filters.releaseYearMax}
                onChange={(event) => updateFilter("releaseYearMax", event.target.value)}
                style={styles.input}
              />
            </label>
            <label style={styles.field}>
              <span>Runtime min</span>
              <input
                inputMode="numeric"
                pattern="[0-9]*"
                value={filters.runtimeMinutesMin}
                onChange={(event) => updateFilter("runtimeMinutesMin", event.target.value)}
                style={styles.input}
              />
            </label>
            <label style={styles.field}>
              <span>Runtime max</span>
              <input
                inputMode="numeric"
                pattern="[0-9]*"
                value={filters.runtimeMinutesMax}
                onChange={(event) => updateFilter("runtimeMinutesMax", event.target.value)}
                style={styles.input}
              />
            </label>
            <label style={styles.field}>
              <span>Minimum evidence count</span>
              <input
                inputMode="numeric"
                pattern="[0-9]*"
                value={filters.minimumEvidenceCount}
                onChange={(event) => updateFilter("minimumEvidenceCount", event.target.value)}
                style={styles.input}
              />
            </label>
            <label style={styles.field}>
              <span>Page size</span>
              <input
                inputMode="numeric"
                pattern="[0-9]*"
                value={filters.pageSize}
                onChange={(event) => updateFilter("pageSize", event.target.value)}
                style={styles.input}
              />
            </label>
          </div>
        </section>

        <section style={styles.section}>
          <h2 style={styles.subheading}>Availability</h2>
          <label style={styles.disabledField}>
            <input type="checkbox" disabled />
            <span>Regional streaming availability (coming later)</span>
          </label>
          <p style={styles.helper}>This control stays disabled until Phase 2G. The UI never submits availability filters in Phase 2D.2.</p>
        </section>

        <div style={styles.actionRow}>
          <button type="submit" style={styles.button} disabled={!canSubmit}>
            {status === "loading" ? "Discovering..." : "Discover movies"}
          </button>
          <button type="button" style={styles.secondaryButton} onClick={onReset} disabled={status === "loading"}>
            Reset filters
          </button>
        </div>
        {!hasMeaningfulNarrowing(filters) ? (
          <p style={styles.helper}>Add a genre, language, year bound, runtime bound, or minimum evidence count above zero before searching.</p>
        ) : null}
      </form>

      {error ? <p style={styles.error}>{error}</p> : null}

      <DiscoveryResultsPanel
        response={response}
        status={status}
        onNextPage={onNextPage}
        onPreviousPage={onPreviousPage}
      />
    </section>
  );
}

function DiscoveryResultsPanel({
  response,
  status,
  onNextPage,
  onPreviousPage,
}: {
  response: DiscoveryResponse | null;
  status: DiscoveryStatus;
  onNextPage: () => void;
  onPreviousPage: () => void;
}) {
  if (status === "idle") {
    return (
      <section style={styles.card}>
        <div style={styles.headline}>
          <div>
            <p style={styles.eyebrow}>Discovery</p>
            <h2 style={styles.resultTitle}>Ready for a structured search</h2>
          </div>
        </div>
        <p style={styles.overview}>Choose at least one narrowing filter, then submit a provider-neutral discovery request.</p>
      </section>
    );
  }

  if (status === "loading") {
    return (
      <section style={styles.card}>
        <div style={styles.headline}>
          <div>
            <p style={styles.eyebrow}>Discovery</p>
            <h2 style={styles.resultTitle}>Ranking discovery results…</h2>
          </div>
        </div>
        <p style={styles.overview}>Waiting for the backend to normalize the request and return ranked matches.</p>
      </section>
    );
  }

  if (!response || response.results.length === 0) {
    return (
      <section style={styles.card}>
        <div style={styles.headline}>
          <div>
            <p style={styles.eyebrow}>Discovery</p>
            <h2 style={styles.resultTitle}>No movies matched these filters</h2>
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

      <article style={styles.panel}>
        <h3 style={styles.sectionTitle}>Normalized Request</h3>
        <p style={styles.small}>Genres: {response.request.genres.length ? response.request.genres.join(", ") : "none"}</p>
        <p style={styles.small}>Original language: {response.request.original_language ?? "none"}</p>
        <p style={styles.small}>Region: {response.request.region ?? "none"}</p>
        <p style={styles.small}>
          Release years: {response.request.release_year_min ?? "?"} to {response.request.release_year_max ?? "?"}
        </p>
        <p style={styles.small}>
          Runtime: {response.request.runtime_minutes_min ?? "?"} to {response.request.runtime_minutes_max ?? "?"} minutes
        </p>
        <p style={styles.small}>Minimum evidence count: {response.request.minimum_evidence_count}</p>
      </article>

      <div style={styles.paginationRow}>
        <button type="button" style={styles.secondaryButton} onClick={onPreviousPage} disabled={previousDisabled}>
          Previous
        </button>
        <button type="button" style={styles.secondaryButton} onClick={onNextPage} disabled={nextDisabled}>
          Next
        </button>
      </div>

      <div style={styles.recommendationList}>
        {response.results.map((item) => (
          <article key={`${item.tmdb_source_movie_id}-${item.movie.movie_id}`} style={styles.recommendationCard}>
            <div style={styles.recommendationHeader}>
              {item.movie.poster_url ? (
                <img
                  src={item.movie.poster_url}
                  alt={`${item.movie.canonical_title} poster`}
                  style={styles.poster}
                />
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
          </article>
        ))}
      </div>
    </section>
  );
}

const styles: Record<string, CSSProperties> = {
  shell: {
    maxWidth: 980,
    margin: "0 auto",
    display: "grid",
    gap: 24,
  },
  hero: {
    padding: "32px 32px 12px",
  },
  kicker: {
    margin: 0,
    color: "var(--accent)",
    letterSpacing: "0.16em",
    textTransform: "uppercase",
    fontSize: 12,
  },
  title: {
    margin: "10px 0 12px",
    fontSize: "clamp(2.2rem, 5vw, 4rem)",
  },
  copy: {
    margin: 0,
    maxWidth: 700,
    color: "var(--muted)",
    lineHeight: 1.7,
  },
  achievementPanel: {
    display: "grid",
    gap: 18,
    padding: "0 32px",
  },
  achievementHeader: {
    display: "flex",
    justifyContent: "space-between",
    gap: 16,
    alignItems: "end",
    flexWrap: "wrap",
  },
  achievementCopy: {
    margin: 0,
    color: "var(--muted)",
  },
  achievementGrid: {
    display: "grid",
    gap: 14,
    gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  },
  achievementCard: {
    borderRadius: 22,
    padding: "18px 20px",
    background: "linear-gradient(180deg, rgba(255,255,255,0.82) 0%, rgba(248,232,213,0.92) 100%)",
    border: "1px solid rgba(141,46,22,0.14)",
    boxShadow: "0 18px 40px rgba(86, 42, 16, 0.08)",
  },
  achievementLabel: {
    margin: 0,
    color: "var(--accent)",
    textTransform: "uppercase",
    letterSpacing: "0.12em",
    fontSize: 11,
  },
  achievementValue: {
    display: "block",
    marginTop: 8,
    fontSize: "clamp(1rem, 2vw, 1.25rem)",
  },
  form: {
    display: "grid",
    gap: 20,
    borderRadius: 28,
    background: "var(--panel)",
    boxShadow: "var(--shadow)",
    padding: 32,
  },
  section: {
    display: "grid",
    gap: 14,
  },
  subheading: {
    margin: 0,
    fontSize: "clamp(1.2rem, 2vw, 1.5rem)",
  },
  genreGrid: {
    display: "grid",
    gap: 10,
    gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
  },
  genreChip: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    padding: "12px 14px",
    borderRadius: 18,
    background: "rgba(255,255,255,0.58)",
    border: "1px solid var(--line)",
  },
  fieldGrid: {
    display: "grid",
    gap: 16,
    gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  },
  field: {
    display: "grid",
    gap: 8,
  },
  input: {
    minHeight: 48,
    borderRadius: 16,
    border: "1px solid var(--line)",
    padding: "0 14px",
    background: "rgba(255,255,255,0.78)",
  },
  disabledField: {
    display: "flex",
    gap: 10,
    alignItems: "center",
    color: "var(--muted)",
  },
  helper: {
    margin: 0,
    color: "var(--muted)",
    lineHeight: 1.6,
  },
  actionRow: {
    display: "flex",
    gap: 12,
    flexWrap: "wrap",
  },
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
  card: {
    display: "grid",
    gap: 20,
    borderRadius: 28,
    background: "var(--panel)",
    boxShadow: "var(--shadow)",
    padding: 32,
  },
  headline: {
    display: "flex",
    justifyContent: "space-between",
    gap: 16,
    alignItems: "start",
    flexWrap: "wrap",
  },
  eyebrow: {
    margin: 0,
    color: "var(--accent)",
    textTransform: "uppercase",
    letterSpacing: "0.16em",
    fontSize: 12,
  },
  resultTitle: {
    margin: "8px 0",
    fontSize: "clamp(2rem, 4vw, 3rem)",
  },
  meta: {
    margin: 0,
    color: "var(--muted)",
  },
  overview: {
    margin: 0,
    lineHeight: 1.6,
    color: "var(--muted)",
  },
  paginationRow: {
    display: "flex",
    gap: 12,
    flexWrap: "wrap",
  },
  recommendationList: {
    display: "grid",
    gap: 20,
  },
  recommendationCard: {
    display: "grid",
    gap: 16,
    borderRadius: 24,
    padding: 24,
    background: "rgba(255,255,255,0.58)",
    border: "1px solid var(--line)",
  },
  recommendationHeader: {
    display: "grid",
    gridTemplateColumns: "88px minmax(0, 1fr)",
    gap: 16,
    alignItems: "start",
  },
  poster: {
    width: 88,
    height: 132,
    objectFit: "cover",
    borderRadius: 16,
    background: "rgba(255,255,255,0.8)",
    border: "1px solid var(--line)",
  },
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
  recommendationIntro: {
    minWidth: 0,
  },
  recommendationTitle: {
    margin: "6px 0 8px",
    fontSize: "clamp(1.5rem, 3vw, 2rem)",
  },
  grid: {
    display: "grid",
    gap: 16,
    gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
  },
  panel: {
    border: "1px solid var(--line)",
    borderRadius: 20,
    padding: 20,
    background: "rgba(255,255,255,0.55)",
  },
  sectionTitle: {
    marginTop: 0,
    marginBottom: 12,
  },
  list: {
    listStyle: "none",
    padding: 0,
    margin: 0,
    display: "grid",
    gap: 10,
  },
  item: {
    display: "flex",
    justifyContent: "space-between",
    gap: 12,
  },
  small: {
    margin: "6px 0",
    color: "var(--muted)",
    lineHeight: 1.5,
  },
};
