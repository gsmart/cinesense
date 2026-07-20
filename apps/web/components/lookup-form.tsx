"use client";

import type { CSSProperties, FormEvent } from "react";
import { useState } from "react";
import { useRouter } from "next/navigation";

import { MovieCard, RecommendationsPanel } from "@/components/movie-card";
import type { LookupResponse, RecommendationsResponse } from "@/lib/types";

export function LookupForm() {
  const router = useRouter();

  // Natural Language Search State
  const [nlQuery, setNlQuery] = useState("");

  // Exact Lookup State
  const [showExact, setShowExact] = useState(false);
  const [title, setTitle] = useState("");
  const [year, setYear] = useState("");
  const [region, setRegion] = useState("");
  const [includeShadow, setIncludeShadow] = useState(false);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<LookupResponse | null>(null);
  const [recommendationStatus, setRecommendationStatus] = useState<"idle" | "loading" | "error" | "success">("idle");
  const [recommendationError, setRecommendationError] = useState<string | null>(null);
  const [recommendations, setRecommendations] = useState<RecommendationsResponse | null>(null);

  const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  const showDiagnosticsToggle = process.env.NEXT_PUBLIC_CINESENSE_ENABLE_SHADOW_DIAGNOSTICS === "true";

  const exampleChips = [
    "Marathi crime thrillers",
    "Movies like Drishyam",
    "Malayalam dramas after 2015",
    "Fast-paced survival movies",
    "Tamil psychological thrillers",
  ];

  function onNLSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (nlQuery.trim()) {
      router.push(`/discover?q=${encodeURIComponent(nlQuery.trim())}`);
    }
  }

  async function onExactSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("loading");
    setError(null);
    setRecommendationStatus("idle");
    setRecommendationError(null);
    setRecommendations(null);
    const payload = {
      title,
      year: year ? Number(year) : null,
      region: region || null,
      media_type: "movie",
      include_shadow: includeShadow,
    };

    const request = await fetch(`${apiBase}/api/v1/lookup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!request.ok) {
      const data = await request.json().catch(() => ({}));
      setStatus("error");
      setError(data.detail ?? "Lookup failed");
      return;
    }

    const data = (await request.json()) as LookupResponse;
    setResponse(data);
    setStatus("idle");
  }

  async function fetchRecommendations() {
    if (response?.status !== "resolved" || !response.movie) return;

    setRecommendationStatus("loading");
    setRecommendationError(null);

    const request = await fetch(`${apiBase}/api/v1/recommendations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        seed_movie_id: response.movie.movie_id,
        region: region || null,
        page_size: 20,
        include_shadow: includeShadow,
      }),
    });

    if (!request.ok) {
      const data = await request.json().catch(() => ({}));
      setRecommendationStatus("error");
      setRecommendationError(data.detail ?? "Recommendation request failed");
      return;
    }

    const data = (await request.json()) as RecommendationsResponse;
    setRecommendations(data);
    setRecommendationStatus("success");
  }

  return (
    <section style={styles.shell}>
      <div style={styles.hero}>
        <h1 style={styles.heroTitle}>What should you watch tonight?</h1>
        <p style={styles.heroCopy}>
          Search by title, mood, genre, language, year, or a movie you already love.
        </p>

        <form onSubmit={onNLSubmit} style={styles.searchForm}>
          <input
            type="text"
            placeholder="e.g. Marathi crime thrillers from the 2010s"
            value={nlQuery}
            onChange={(e) => setNlQuery(e.target.value)}
            style={styles.searchInput}
          />
          <button type="submit" className="interactive" style={styles.searchButton}>Discover</button>
        </form>

        <div style={styles.chipList}>
          {exampleChips.map((chip) => (
            <button
              key={chip}
              type="button"
              className="interactive"
              style={styles.chip}
              onClick={() => {
                setNlQuery(chip);
                router.push(`/discover?q=${encodeURIComponent(chip)}`);
              }}
            >
              {chip}
            </button>
          ))}
        </div>
      </div>

      <div style={styles.toggleContainer}>
        <button
          type="button"
          className="interactive"
          onClick={() => setShowExact(!showExact)}
          style={styles.exactToggle}
        >
          {showExact ? "Hide exact title search" : "Looking for a specific exact title?"}
        </button>
      </div>

      {showExact && (
        <form onSubmit={onExactSubmit} style={styles.form}>
          <div style={styles.formHeader}>
            <h2 style={styles.formTitle}>Exact Title Lookup</h2>
          </div>
          <div style={styles.fieldGrid}>
            <label style={styles.field}>
              <span>Movie title</span>
              <input
                required
                placeholder="e.g. Faster Fene"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                style={styles.input}
              />
            </label>
            <label style={styles.field}>
              <span>Release year (optional)</span>
              <input
                type="number"
                min={1888}
                max={2100}
                placeholder="e.g. 2017"
                value={year}
                onChange={(event) => setYear(event.target.value)}
                style={styles.input}
              />
            </label>
            <label style={styles.field}>
              <span>Region</span>
              <input
                maxLength={2}
                value={region}
                onChange={(event) => setRegion(event.target.value.toUpperCase())}
                style={styles.input}
                placeholder="e.g. IN"
              />
            </label>
            <label style={styles.field}>
              <span>Media type</span>
              <select value="movie" disabled style={styles.input}>
                <option value="movie">movie</option>
              </select>
            </label>
          </div>
          {showDiagnosticsToggle && (
            <label style={{ ...styles.field, display: "flex", flexDirection: "row", alignItems: "center", gap: 10, cursor: "pointer", marginTop: 16 }}>
              <input
                id="enable-shadow-diagnostics"
                type="checkbox"
                checked={includeShadow}
                onChange={(event) => setIncludeShadow(event.target.checked)}
                style={{ width: 20, height: 20, cursor: "pointer" }}
              />
              <span style={{ fontWeight: 500, color: "var(--text)" }}>Enable Shadow Diagnostics (v2)</span>
            </label>
          )}
          <div style={styles.formActions}>
            <button type="submit" className="interactive" style={styles.button} disabled={status === "loading"}>
              {status === "loading" ? "Looking up..." : "Lookup"}
            </button>
          </div>
        </form>
      )}

      {error && <p style={styles.error}>{error}</p>}

      {response?.status === "disambiguation" ? (
        <section style={styles.resultPanel}>
          <h2 style={{ marginTop: 0 }}>Disambiguation needed</h2>
          <p style={{ color: "var(--muted)" }}>Multiple exact-title matches exist for `{response.normalized_title}`.</p>
          <ul style={styles.choiceList}>
            {response.disambiguation_choices.map((choice) => (
              <li key={`${choice.source}-${choice.source_movie_id}`} style={styles.choice}>
                <strong>{choice.title}</strong> {choice.release_year ? `(${choice.release_year})` : ""}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {response?.status === "resolved" && response.movie ? (
        <>
          <MovieCard
            response={response}
            onFindSimilar={fetchRecommendations}
            recommendationStatus={recommendationStatus}
          />
          <RecommendationsPanel
            response={recommendations}
            status={recommendationStatus}
            error={recommendationError}
            onRetry={fetchRecommendations}
          />
        </>
      ) : null}
    </section>
  );
}

const styles: Record<string, CSSProperties> = {
  shell: {
    maxWidth: 1024,
    margin: "0 auto",
    display: "flex",
    flexDirection: "column",
    gap: 32,
    padding: "40px 0",
  },
  hero: {
    textAlign: "center",
    padding: "64px 20px 48px",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
  },
  heroTitle: {
    margin: "0 0 16px",
    fontSize: "clamp(2.5rem, 6vw, 4.5rem)",
    fontWeight: 800,
    letterSpacing: "-0.03em",
    lineHeight: 1.1,
  },
  heroCopy: {
    margin: "0 0 40px",
    fontSize: "clamp(1.1rem, 2vw, 1.4rem)",
    color: "var(--muted)",
    maxWidth: 600,
  },
  searchForm: {
    display: "flex",
    width: "100%",
    maxWidth: 720,
    gap: 8,
    background: "var(--surface)",
    padding: 8,
    borderRadius: 999,
    border: "1px solid var(--line)",
    boxShadow: "var(--shadow)",
    backdropFilter: "blur(20px)",
  },
  searchInput: {
    flex: 1,
    background: "transparent",
    border: "none",
    color: "var(--text)",
    padding: "0 24px",
    fontSize: "1.1rem",
    outline: "none",
  },
  searchButton: {
    padding: "16px 36px",
    borderRadius: 999,
    border: "none",
    background: "var(--accent)",
    color: "#fff",
    fontSize: "1.1rem",
    fontWeight: 600,
    cursor: "pointer",
  },
  chipList: {
    display: "flex",
    flexWrap: "wrap",
    gap: 12,
    justifyContent: "center",
    marginTop: 32,
    maxWidth: 800,
  },
  chip: {
    padding: "8px 16px",
    borderRadius: 999,
    background: "var(--surface)",
    border: "1px solid var(--line)",
    color: "var(--text)",
    fontSize: 14,
    cursor: "pointer",
  },
  toggleContainer: {
    display: "flex",
    justifyContent: "center",
  },
  exactToggle: {
    background: "none",
    border: "none",
    color: "var(--muted)",
    textDecoration: "underline",
    cursor: "pointer",
    fontSize: 15,
  },
  form: {
    display: "flex",
    flexDirection: "column",
    gap: 24,
    padding: 32,
    borderRadius: 24,
    background: "var(--panel)",
    border: "1px solid var(--line)",
    boxShadow: "var(--shadow)",
    backdropFilter: "blur(20px)",
  },
  formHeader: {
    marginBottom: 8,
  },
  formTitle: {
    margin: 0,
    fontSize: 24,
    fontWeight: 600,
  },
  fieldGrid: {
    display: "grid",
    gap: 16,
    gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
  },
  field: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
    color: "var(--muted)",
    fontSize: 14,
  },
  input: {
    minHeight: 48,
    borderRadius: 12,
    border: "1px solid var(--line)",
    background: "var(--surface-elevated)",
    padding: "0 16px",
    color: "var(--text)",
  },
  formActions: {
    display: "flex",
    justifyContent: "flex-end",
    marginTop: 8,
  },
  button: {
    minHeight: 48,
    borderRadius: 999,
    border: "none",
    background: "var(--accent)",
    color: "#fff",
    padding: "0 32px",
    fontWeight: 600,
    cursor: "pointer",
  },
  error: {
    color: "var(--error-text)",
    background: "var(--error-bg)",
    padding: "16px 24px",
    borderRadius: 12,
    border: "1px solid var(--error-border)",
    margin: 0,
  },
  resultPanel: {
    borderRadius: 24,
    background: "var(--panel)",
    border: "1px solid var(--line)",
    padding: 32,
  },
  choiceList: {
    margin: "16px 0 0",
    paddingLeft: 24,
    display: "grid",
    gap: 12,
  },
  choice: {
    color: "var(--text)",
  },
};
