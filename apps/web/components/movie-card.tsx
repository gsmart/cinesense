import type { CSSProperties } from "react";

import type { LookupResponse } from "@/lib/types";

export function MovieCard({ response }: { response: LookupResponse }) {
  if (response.status !== "resolved" || !response.movie) {
    return null;
  }

  const { movie } = response;

  return (
    <section style={styles.card}>
      <div style={styles.headline}>
        <div>
          <p style={styles.eyebrow}>{response.source === "local_cache" ? "Warm cache" : "Fresh provider fetch"}</p>
          <h2 style={styles.title}>
            {movie.canonical_title} {movie.release_year ? `(${movie.release_year})` : ""}
          </h2>
          <p style={styles.meta}>
            {movie.media_type} · {movie.original_language ?? "unknown language"} · {movie.runtime_minutes ?? "?"} min
          </p>
        </div>
        <div style={styles.score}>
          <span style={styles.scoreLabel}>{movie.score.version}</span>
          <strong>{movie.score.total.toFixed(2)}</strong>
        </div>
      </div>

      <p style={styles.overview}>{movie.overview || "No overview was returned."}</p>

      <div style={styles.grid}>
        <article style={styles.panel}>
          <h3 style={styles.sectionTitle}>Score Breakdown</h3>
          <ul style={styles.list}>
            {Object.entries(movie.score.components).map(([key, value]) => (
              <li key={key} style={styles.item}>
                <span>{key}</span>
                <strong>{value === null ? "missing" : value.toFixed(2)}</strong>
              </li>
            ))}
          </ul>
        </article>

        <article style={styles.panel}>
          <h3 style={styles.sectionTitle}>Freshness</h3>
          <ul style={styles.list}>
            {Object.entries(movie.freshness).map(([key, value]) => (
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
          <h3 style={styles.sectionTitle}>Provenance</h3>
          <p style={styles.small}>Source: {movie.source}</p>
          <p style={styles.small}>Source ID: {movie.source_movie_id}</p>
          <p style={styles.small}>
            Source URL:{" "}
            {movie.source_url ? (
              <a href={movie.source_url} target="_blank" rel="noreferrer">
                {movie.source_url}
              </a>
            ) : (
              "unavailable"
            )}
          </p>
        </article>

        <article style={styles.panel}>
          <h3 style={styles.sectionTitle}>Missing Signals</h3>
          <p style={styles.small}>
            {movie.missing_signals.length ? movie.missing_signals.join(", ") : "None"}
          </p>
          <h3 style={styles.sectionTitle}>Aliases</h3>
          <p style={styles.small}>{movie.aliases.join(", ")}</p>
        </article>
      </div>
    </section>
  );
}

const styles: Record<string, CSSProperties> = {
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
  title: {
    margin: "8px 0",
    fontSize: "clamp(2rem, 4vw, 3rem)",
  },
  meta: {
    margin: 0,
    color: "var(--muted)",
  },
  score: {
    minWidth: 120,
    display: "grid",
    placeItems: "center",
    padding: 18,
    borderRadius: 24,
    background: "var(--accent-soft)",
  },
  scoreLabel: {
    color: "var(--muted)",
    fontSize: 12,
    textTransform: "uppercase",
    letterSpacing: "0.1em",
  },
  overview: {
    margin: 0,
    lineHeight: 1.6,
    color: "var(--muted)",
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
