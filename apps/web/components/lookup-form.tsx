"use client";

import type { CSSProperties, FormEvent } from "react";
import { useState } from "react";

import { MovieCard, RecommendationsPanel } from "@/components/movie-card";
import type { LookupResponse, RecommendationsResponse } from "@/lib/types";

const initialResponse: LookupResponse | null = null;

function buildAchievements(
  response: LookupResponse | null,
  recommendationStatus: "idle" | "loading" | "error" | "success",
  recommendations: RecommendationsResponse | null,
) {
  const achievements = [
    { label: "Exact lookup", value: response?.status === "resolved" ? "Working" : "Ready" },
    {
      label: "Data source",
      value:
        response?.status === "resolved"
          ? response.source === "local_cache"
            ? "Warm cache reused"
            : "Provider fetch stored"
          : "PostgreSQL first",
    },
    {
      label: "Score engine",
      value: response?.status === "resolved" ? response.movie?.score.version ?? "cine-score-v1" : "cine-score-v1",
    },
    {
      label: "Recommendations",
      value:
        recommendationStatus === "success"
          ? `${recommendations?.page.returned_count ?? 0} ranked results`
          : recommendationStatus === "loading"
            ? "Ranking in progress"
            : "On demand",
    },
  ];

  if (response?.status === "disambiguation") {
    achievements[0] = { label: "Disambiguation", value: `${response.disambiguation_choices.length} choices` };
  }

  return achievements;
}

export function LookupForm() {
  const [title, setTitle] = useState("");
  const [year, setYear] = useState("");
  const [region, setRegion] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<LookupResponse | null>(initialResponse);
  const [recommendationStatus, setRecommendationStatus] = useState<"idle" | "loading" | "error" | "success">("idle");
  const [recommendationError, setRecommendationError] = useState<string | null>(null);
  const [recommendations, setRecommendations] = useState<RecommendationsResponse | null>(null);

  const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  const achievements = buildAchievements(response, recommendationStatus, recommendations);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
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
    if (response?.status !== "resolved" || !response.movie) {
      return;
    }

    setRecommendationStatus("loading");
    setRecommendationError(null);

    const request = await fetch(`${apiBase}/api/v1/recommendations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        seed_movie_id: response.movie.movie_id,
        region: region || null,
        page_size: 20,
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
        <p style={styles.kicker}>Phase 1A MVP</p>
        <h1 style={styles.title}>Exact movie lookup, local first.</h1>
        <p style={styles.copy}>
          Search by exact title, optionally narrow by year and region, and inspect what was cached,
          what was fetched, and which signals are still missing.
        </p>
      </div>

      <section style={styles.achievementPanel}>
        <div style={styles.achievementHeader}>
          <p style={styles.kicker}>Achievements</p>
          <p style={styles.achievementCopy}>Surface the system wins directly in the UI, not just in the docs.</p>
        </div>
        <div style={styles.achievementGrid}>
          {achievements.map((achievement) => (
            <article key={achievement.label} style={styles.achievementCard}>
              <p style={styles.achievementLabel}>{achievement.label}</p>
              <strong style={styles.achievementValue}>{achievement.value}</strong>
            </article>
          ))}
        </div>
      </section>

      <form onSubmit={onSubmit} style={styles.form}>
        <label style={styles.field}>
          <span>Title</span>
          <input required value={title} onChange={(event) => setTitle(event.target.value)} style={styles.input} />
        </label>
        <label style={styles.field}>
          <span>Release year</span>
          <input
            inputMode="numeric"
            pattern="[0-9]*"
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
          />
        </label>
        <label style={styles.field}>
          <span>Media type</span>
          <select value="movie" disabled style={styles.input}>
            <option value="movie">movie</option>
          </select>
        </label>
        <button type="submit" style={styles.button} disabled={status === "loading"}>
          {status === "loading" ? "Looking up..." : "Lookup"}
        </button>
      </form>

      {error ? <p style={styles.error}>{error}</p> : null}

      {response?.status === "disambiguation" ? (
        <section style={styles.resultPanel}>
          <h2 style={styles.subheading}>Disambiguation needed</h2>
          <p style={styles.copy}>Multiple exact-title matches exist for `{response.normalized_title}`.</p>
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
    maxWidth: 980,
    margin: "0 auto",
    display: "grid",
    gap: 24,
  },
  hero: {
    padding: "32px 32px 12px",
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
  kicker: {
    margin: 0,
    color: "var(--accent)",
    letterSpacing: "0.16em",
    textTransform: "uppercase",
    fontSize: 12,
  },
  title: {
    margin: "10px 0 12px",
    fontSize: "clamp(2.4rem, 5vw, 4.8rem)",
    lineHeight: 0.95,
  },
  copy: {
    margin: 0,
    maxWidth: 720,
    color: "var(--muted)",
    lineHeight: 1.5,
  },
  form: {
    display: "grid",
    gap: 16,
    gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
    padding: 32,
    borderRadius: 28,
    background: "var(--panel)",
    boxShadow: "var(--shadow)",
    backdropFilter: "blur(20px)",
  },
  field: {
    display: "grid",
    gap: 8,
    color: "var(--muted)",
  },
  input: {
    minHeight: 48,
    borderRadius: 16,
    border: "1px solid var(--line)",
    background: "rgba(255,255,255,0.88)",
    padding: "0 14px",
    color: "var(--text)",
  },
  button: {
    minHeight: 48,
    borderRadius: 999,
    border: 0,
    background: "linear-gradient(135deg, #8d2e16 0%, #c85f33 100%)",
    color: "#fff8f0",
    padding: "0 24px",
    cursor: "pointer",
    alignSelf: "end",
  },
  error: {
    margin: 0,
    color: "#872017",
  },
  resultPanel: {
    borderRadius: 28,
    background: "var(--panel)",
    boxShadow: "var(--shadow)",
    padding: 32,
  },
  subheading: {
    marginTop: 0,
  },
  choiceList: {
    margin: 0,
    paddingLeft: 20,
    display: "grid",
    gap: 8,
  },
  choice: {
    color: "var(--text)",
  },
};
