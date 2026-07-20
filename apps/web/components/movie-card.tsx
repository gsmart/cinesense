import type { CSSProperties } from "react";
import { CollapsiblePanel } from "./collapsible-panel";
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
  const isCache = response.source === "local_cache";

  return (
    <section style={styles.cinematicCard}>
      <div style={styles.detailLayout}>
        <div style={styles.posterColumn}>
          {movie.poster_url ? (
            <img src={movie.poster_url} alt={`${movie.canonical_title} poster`} style={styles.detailPoster} />
          ) : (
            <div style={styles.detailPosterFallback}>No poster available</div>
          )}
        </div>
        <div style={styles.infoColumn}>
          <div style={styles.headline}>
            <div>
              <h2 style={styles.title}>
                {movie.canonical_title} {movie.release_year ? <span style={{ color: "var(--muted)", fontWeight: 400 }}>({movie.release_year})</span> : ""}
              </h2>
              <p style={styles.meta}>
                {movie.runtime_minutes ? `${movie.runtime_minutes} min` : "Unknown runtime"} • {movie.original_language?.toUpperCase() || "UN"}
              </p>
            </div>
            <div style={styles.scoreBadge}>
              <strong style={styles.scoreValue}>{movie.score.total.toFixed(2)}</strong>
              <span style={styles.scoreLabel}>CineSense</span>
            </div>
          </div>
          <p style={styles.overview}>{movie.overview || "No overview available."}</p>

          {onFindSimilar ? (
            <div style={styles.actionRow}>
              <button
                type="button"
                className="interactive"
                style={styles.primaryAction}
                disabled={recommendationStatus === "loading"}
                onClick={onFindSimilar}
              >
                {recommendationStatus === "loading" ? "Finding similar movies..." : "Find similar movies"}
              </button>
            </div>
          ) : null}

          <div style={styles.collapsibleSections}>
            <CollapsiblePanel title="Score explanation">
              <ul style={styles.list}>
                {Object.entries(movie.score.components).map(([key, value]) => (
                  <li key={key} style={styles.item}>
                    <span>{key}</span>
                    <strong>{value === null ? "missing" : value.toFixed(2)}</strong>
                  </li>
                ))}
              </ul>
            </CollapsiblePanel>

            <CollapsiblePanel title="Freshness">
              <ul style={styles.list}>
                <li style={styles.item}>
                  <span>Data Source</span>
                  <strong>{isCache ? "Local Cache" : "Fresh Provider Fetch"}</strong>
                </li>
                {Object.entries(movie.freshness).map(([key, value]) => (
                  <li key={key} style={styles.item}>
                    <span>{key}</span>
                    <strong>{value}</strong>
                  </li>
                ))}
              </ul>
            </CollapsiblePanel>

            <CollapsiblePanel title="Provenance & Aliases">
              <p style={styles.small}><strong>Source:</strong> {movie.source} ({movie.source_movie_id})</p>
              {movie.source_url && (
                <p style={styles.small}>
                  <strong>URL:</strong> <a href={movie.source_url} target="_blank" rel="noreferrer" style={styles.link}>{movie.source_url}</a>
                </p>
              )}
              {movie.aliases.length > 0 && (
                <p style={styles.small}><strong>Aliases:</strong> {movie.aliases.join(", ")}</p>
              )}
            </CollapsiblePanel>

            <CollapsiblePanel title="Missing Signals">
              <p style={styles.small}>
                {movie.missing_signals.length ? movie.missing_signals.join(", ") : "None"}
              </p>
            </CollapsiblePanel>

            {movie.shadow_comparison && (
              <CollapsiblePanel title="Developer ranking diagnostics" headerColor="var(--accent)">
                <div style={styles.diagnosticGrid}>
                  <div>
                    <p style={styles.small}><strong>Shadow Version:</strong> {movie.shadow_comparison.score_version}</p>
                    <p style={styles.small}>
                      <strong>V2 Score:</strong> {movie.shadow_comparison.v2_score !== null ? movie.shadow_comparison.v2_score.toFixed(2) : "N/A"}
                    </p>
                    <p style={styles.small}>
                      <strong>Authoritative:</strong> {movie.shadow_comparison.authoritative ? "Yes" : "No"}
                    </p>
                  </div>
                  <div>
                    <p style={styles.small}><strong>Evidence Gate:</strong> {movie.shadow_comparison.evidence_gate || "N/A"}</p>
                    <p style={styles.small}><strong>Human Review:</strong> {movie.shadow_comparison.review_status || "PENDING"}</p>
                    <p style={styles.small}><strong>Activation Eligible:</strong> {movie.shadow_comparison.activation_eligible ? "Yes" : "No"}</p>
                    {movie.shadow_comparison.ineligible_reason && (
                      <p style={{ ...styles.small, color: "var(--accent)" }}><strong>Ineligible:</strong> {movie.shadow_comparison.ineligible_reason}</p>
                    )}
                  </div>
                </div>
              </CollapsiblePanel>
            )}
          </div>
        </div>
      </div>
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
  if (status === "idle") return null;

  if (status === "loading") {
    return (
      <section style={styles.recommendationsSection}>
        <h2 style={styles.sectionHeading}>Finding similar movies…</h2>
        <div style={styles.posterGrid}>
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} style={styles.skeletonCard} />
          ))}
        </div>
      </section>
    );
  }

  if (status === "error") {
    return (
      <section style={styles.recommendationsSection}>
        <h2 style={styles.sectionHeading}>Recommendations failed</h2>
        <p style={{ color: "var(--muted)" }}>{error}</p>
        <button type="button" className="interactive" style={styles.secondaryAction} onClick={onRetry}>Retry</button>
      </section>
    );
  }

  if (!response || response.recommendations.length === 0) {
    return (
      <section style={styles.recommendationsSection}>
        <h2 style={styles.sectionHeading}>No similar movies returned</h2>
      </section>
    );
  }

  return (
    <section style={styles.recommendationsSection}>
      <h2 style={styles.sectionHeading}>Similar movies for {response.seed.canonical_title}</h2>

      <div style={styles.posterGrid}>
        {response.recommendations.slice(0, 20).map((item) => (
          <article key={item.movie.movie_id} className="interactive" style={styles.posterCard}>
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
  cinematicCard: {
    background: "var(--panel)",
    borderRadius: 24,
    boxShadow: "var(--shadow)",
    overflow: "hidden",
    backdropFilter: "blur(20px)",
    border: "1px solid var(--line)",
  },
  detailLayout: {
    display: "flex",
    flexDirection: "row",
    gap: 32,
    padding: 32,
    flexWrap: "wrap",
  },
  posterColumn: {
    flex: "0 0 300px",
  },
  detailPoster: {
    width: "100%",
    aspectRatio: "2/3",
    objectFit: "cover",
    borderRadius: 16,
    boxShadow: "var(--shadow)",
  },
  detailPosterFallback: {
    width: "100%",
    aspectRatio: "2/3",
    borderRadius: 16,
    backgroundColor: "var(--surface)",
    display: "flex",
    placeItems: "center",
    color: "var(--muted)",
    border: "1px dashed var(--line)",
  },
  infoColumn: {
    flex: "1 1 300px",
    display: "flex",
    flexDirection: "column",
    gap: 20,
  },
  headline: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 16,
    flexWrap: "wrap",
  },
  title: {
    margin: "0 0 8px 0",
    fontSize: "clamp(2rem, 4vw, 3rem)",
    fontWeight: 700,
    letterSpacing: "-0.02em",
  },
  meta: {
    margin: 0,
    fontSize: 15,
    color: "var(--muted)",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
  },
  scoreBadge: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    background: "var(--accent-soft)",
    border: "1px solid rgba(217, 119, 54, 0.3)",
    borderRadius: 16,
    padding: "12px 20px",
    minWidth: 100,
  },
  scoreValue: {
    fontSize: 28,
    fontWeight: 700,
    color: "var(--accent)",
    lineHeight: 1,
  },
  scoreLabel: {
    fontSize: 10,
    textTransform: "uppercase",
    letterSpacing: "0.1em",
    marginTop: 6,
    color: "var(--muted)",
  },
  overview: {
    margin: 0,
    fontSize: 16,
    lineHeight: 1.6,
    color: "var(--text)",
  },
  actionRow: {
    display: "flex",
    gap: 12,
    marginTop: 8,
    marginBottom: 8,
  },
  primaryAction: {
    background: "var(--accent)",
    color: "#fff",
    border: "none",
    padding: "12px 24px",
    borderRadius: 999,
    fontSize: 16,
    fontWeight: 600,
    cursor: "pointer",
  },
  secondaryAction: {
    background: "var(--surface)",
    color: "var(--text)",
    border: "1px solid var(--line)",
    padding: "10px 20px",
    borderRadius: 999,
    fontSize: 14,
    fontWeight: 500,
    cursor: "pointer",
    marginTop: 16,
  },
  collapsibleSections: {
    display: "flex",
    flexDirection: "column",
    gap: 12,
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
    fontSize: 14,
    color: "var(--text)",
  },
  small: {
    margin: "4px 0",
    fontSize: 13,
    color: "var(--muted)",
  },
  link: {
    color: "var(--accent)",
    textDecoration: "none",
  },
  diagnosticGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
    gap: 16,
  },
  recommendationsSection: {
    marginTop: 24,
  },
  sectionHeading: {
    fontSize: 24,
    marginBottom: 20,
    fontWeight: 600,
  },
  posterGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
    gap: 20,
  },
  skeletonCard: {
    aspectRatio: "2/3",
    borderRadius: 16,
    background: "var(--surface)",
    animation: "pulse 2s infinite",
  },
  posterCard: {
    display: "flex",
    flexDirection: "column",
    gap: 12,
    cursor: "pointer",
  },
  posterWrapper: {
    position: "relative",
    aspectRatio: "2/3",
    borderRadius: 16,
    overflow: "hidden",
    boxShadow: "var(--shadow)",
    backgroundColor: "var(--surface)",
  },
  cardPoster: {
    width: "100%",
    height: "100%",
    objectFit: "cover",
  },
  cardPosterFallback: {
    width: "100%",
    height: "100%",
    background: "var(--surface)",
    display: "grid",
    placeItems: "center",
    color: "var(--muted)",
    fontSize: 12,
  },
  cardOverlay: {
    position: "absolute",
    top: 8,
    right: 8,
    display: "flex",
    alignItems: "center",
  },
  cardScore: {
    background: "var(--panel)",
    color: "var(--accent)",
    padding: "4px 8px",
    borderRadius: 8,
    fontSize: 13,
    fontWeight: 700,
    boxShadow: "var(--shadow)",
  },
  cardInfo: {
    display: "flex",
    flexDirection: "column",
    gap: 4,
  },
  cardTitle: {
    margin: 0,
    fontSize: 15,
    fontWeight: 600,
    lineHeight: 1.2,
    display: "-webkit-box",
    WebkitLineClamp: 2,
    WebkitBoxOrient: "vertical",
    overflow: "hidden",
  },
  cardMeta: {
    margin: 0,
    fontSize: 13,
    color: "var(--muted)",
  },
  cardHoverActions: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: 4,
  },
  tooltipIcon: {
    cursor: "help",
    fontSize: 12,
    opacity: 0.5,
  },
  textAction: {
    background: "none",
    border: "none",
    color: "var(--accent)",
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
    padding: 0,
  }
};
