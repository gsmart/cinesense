export type LookupResponse =
  | {
      status: "disambiguation";
      normalized_title: string;
      region: string | null;
      media_type: "movie";
      source: "local_cache" | "tmdb";
      disambiguation_choices: Array<{
        movie_id: string;
        title: string;
        release_year: number | null;
        source: string;
        source_movie_id: string;
      }>;
      movie: null;
    }
  | {
      status: "resolved";
      normalized_title: string;
      region: string | null;
      media_type: "movie";
      source: "local_cache" | "tmdb";
      disambiguation_choices: [];
      movie: {
        movie_id: string;
        canonical_title: string;
        release_year: number | null;
        media_type: string;
        original_language: string | null;
        overview: string | null;
        runtime_minutes: number | null;
        poster_url: string | null;
        aliases: string[];
        source: string;
        source_movie_id: string;
        source_url: string | null;
        freshness: Record<string, string>;
        observations: Array<{
          signal_type: string;
          source: string;
          fetched_at: string;
          fresh_until: string | null;
          stale_until: string | null;
          freshness_state: string;
          value: Record<string, unknown>;
          scale: string | null;
          evidence_count: number | null;
          source_url: string | null;
          fetch_status: string;
        }>;
        missing_signals: string[];
        score: {
          version: string;
          total: number;
          components: Record<string, number | null>;
          missing_signals: string[];
        };
      };
    };

