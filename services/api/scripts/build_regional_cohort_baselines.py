from __future__ import annotations

import argparse
from pathlib import Path

from app.regional_cohort_baselines import (
    DEFAULT_OUTPUT_ROOT,
    CohortBaselineConfig,
    build_regional_cohort_baselines,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build deterministic offline regional cohort baselines.")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--review-file", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = CohortBaselineConfig(output_root=DEFAULT_OUTPUT_ROOT)
    try:
        result = build_regional_cohort_baselines(
            run_dir=args.run_dir,
            output_dir=args.output_dir,
            review_file=args.review_file,
            config=config,
        )
    except Exception as exc:
        print(f"baseline_build_error={exc.__class__.__name__}:{exc}")
        return 1

    coverage = result["coverage_report"]
    print(f"run_id={result['input_run_id']}")
    print(f"output_dir={result['output_dir']}")
    print(f"manual_review_status={result['manual_review_status']}")
    print(f"activation_eligible={result['activation_eligible']}")
    print(f"movies_processed={coverage['total_movies']}")
    print(f"assignments_produced={len(result['movie_assignments'])}")
    print(f"cohort_counts_by_level={coverage['cohort_counts_by_level']}")
    print(f"eligible_cohort_counts_by_level={coverage['eligible_cohort_counts_by_level']}")
    print(f"sparse_cohort_counts_by_level={coverage['sparse_cohort_counts_by_level']}")
    print(f"fallback_counts={coverage['fallback_counts']}")
    print(f"signal_coverage={coverage['signal_coverage']}")
    print(f"per_language_readiness={coverage['per_language_readiness']}")
    print(f"phase_recommendation={result['phase_recommendation']}")
    print(f"input_file_hashes={result['input_file_hashes']}")
    print(f"output_file_hashes={result['output_file_hashes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
