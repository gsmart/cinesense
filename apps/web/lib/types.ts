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

export type RecommendationsResponse = {
  status: "ok";
  seed: {
    movie_id: string;
    canonical_title: string;
    release_year: number | null;
    media_type: string;
  };
  region: string | null;
  limit: number;
  recommendations: Array<{
    movie: {
      movie_id: string;
      canonical_title: string;
      release_year: number | null;
      media_type: string;
      original_language: string | null;
      overview: string | null;
      poster_url: string | null;
    };
    tmdb_source_movie_id: string;
    provider_position: number;
    score: number;
    score_version: string;
    score_components: Record<string, number | null>;
    missing_signals: string[];
    provenance: {
      source: string;
      source_movie_id: string;
      source_url: string | null;
    };
    freshness: Record<string, string>;
  }>;
  page: {
    page: 1;
    requested_page_size: number;
    returned_count: number;
    max_page_size: 20;
  };
};

export type DiscoveryRequestPayload = {
  media_type: "movie";
  genres?: string[];
  original_language?: string;
  region?: string;
  release_year_min?: number;
  release_year_max?: number;
  runtime_minutes_min?: number;
  runtime_minutes_max?: number;
  minimum_evidence_count?: number;
  availability_required?: boolean;
  page: number;
  page_size: number;
};

export type DiscoveryResponse = {
  status: "ok";
  request: {
    media_type: "movie";
    genres: string[];
    original_language: string | null;
    region: string | null;
    release_year_min: number | null;
    release_year_max: number | null;
    runtime_minutes_min: number | null;
    runtime_minutes_max: number | null;
    minimum_evidence_count: number;
    availability_required: boolean;
    page: number;
    page_size: number;
  };
  results: Array<{
    movie: {
      movie_id: string;
      canonical_title: string;
      release_year: number | null;
      media_type: string;
      original_language: string | null;
      overview: string | null;
      poster_url: string | null;
    };
    tmdb_source_movie_id: string;
    provider_position: number;
    score: number;
    score_version: string;
    score_components: Record<string, number | null>;
    missing_signals: string[];
    provenance: {
      source: string;
      source_movie_id: string;
      source_url: string | null;
    };
    freshness: Record<string, string>;
  }>;
  page: {
    page: number;
    requested_page_size: number;
    returned_count: number;
    max_page_size: 20;
  };
};
