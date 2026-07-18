import type { CSSProperties } from "react";

import type { LookupResponse, RecommendationsResponse } from "@/lib/types";

export function MovieCard({
  response,
  onFindSimilar,
  recommendationStatus = "idle",
}: {
  response: LookupResponse;
  onFindSimilar?: () => void;
  recommendationStatus?: "idle" | "loading" | "error" | "success";
}) {
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

      {onFindSimilar ? (
        <div style={styles.actionRow}>
          <button
            type="button"
            style={styles.button}
            disabled={recommendationStatus === "loading"}
            onClick={onFindSimilar}
          >
            {recommendationStatus === "loading" ? "Finding similar movies..." : "Find similar movies"}
          </button>
        </div>
      ) : null}
    </section>
  );
}

export function RecommendationsPanel({
  response,
  status,
  error,
  onRetry,
}: {
  response: RecommendationsResponse | null;
  status: "idle" | "loading" | "error" | "success";
  error: string | null;
  onRetry: () => void;
}) {
  if (status === "idle") {
    return null;
  }

  if (status === "loading") {
    return (
      <section style={styles.card}>
        <div style={styles.headline}>
          <div>
            <p style={styles.eyebrow}>Recommendations</p>
            <h2 style={styles.title}>Finding similar movies…</h2>
          </div>
        </div>
        <p style={styles.overview}>Requesting ranked recommendations from the backend.</p>
      </section>
    );
  }

  if (status === "error") {
    return (
      <section style={styles.card}>
        <div style={styles.headline}>
          <div>
            <p style={styles.eyebrow}>Recommendations</p>
            <h2 style={styles.title}>Request failed</h2>
          </div>
        </div>
        <p style={styles.overview}>{error ?? "Recommendations failed."}</p>
        <div style={styles.actionRow}>
          <button type="button" style={styles.button} onClick={onRetry}>
            Retry
          </button>
        </div>
      </section>
    );
  }

  if (!response || response.recommendations.length === 0) {
    return (
      <section style={styles.card}>
        <div style={styles.headline}>
          <div>
            <p style={styles.eyebrow}>Recommendations</p>
            <h2 style={styles.title}>No similar movies returned</h2>
          </div>
        </div>
        <p style={styles.overview}>The backend returned an empty first recommendation page for this seed movie.</p>
      </section>
    );
  }

  return (
    <section style={styles.card}>
      <div style={styles.headline}>
        <div>
          <p style={styles.eyebrow}>Recommendations</p>
          <h2 style={styles.title}>Similar movies for {response.seed.canonical_title}</h2>
          <p style={styles.meta}>
            page {response.page.page} · requested {response.page.requested_page_size} · returned{" "}
            {response.page.returned_count}
          </p>
        </div>
      </div>

      <div style={styles.recommendationList}>
        {response.recommendations.slice(0, 20).map((item) => (
          <article key={item.movie.movie_id} style={styles.recommendationCard}>
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
  actionRow: {
    display: "flex",
    justifyContent: "flex-start",
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
};
