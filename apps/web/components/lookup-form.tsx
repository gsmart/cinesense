"use client";

import type { CSSProperties, FormEvent } from "react";
import { useState } from "react";

import { MovieCard } from "@/components/movie-card";
import type { LookupResponse } from "@/lib/types";

const initialResponse: LookupResponse | null = null;

export function LookupForm() {
  const [title, setTitle] = useState("");
  const [year, setYear] = useState("");
  const [region, setRegion] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<LookupResponse | null>(initialResponse);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("loading");
    setError(null);

    const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
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

      {response?.status === "resolved" && response.movie ? <MovieCard response={response} /> : null}
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
