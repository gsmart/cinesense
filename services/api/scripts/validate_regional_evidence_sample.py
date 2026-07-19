from __future__ import annotations

import argparse
from pathlib import Path

from app.regional_evidence_validation import (
    BLOCKED_BY_DATA_INTEGRITY,
    BLOCKED_BY_LOW_COVERAGE,
    DEFAULT_MAXIMUM_AMBIGUOUS_ERROR_RATE,
    DEFAULT_MINIMUM_EXACT_COVERAGE,
    DEFAULT_REVIEW_SAMPLE_SIZE,
    ValidationThresholds,
    validate_regional_evidence_run,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate an offline regional evidence sample.")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--review-sample-size", type=int, default=DEFAULT_REVIEW_SAMPLE_SIZE)
    parser.add_argument("--review-file", type=Path, default=None)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--minimum-exact-coverage", type=float, default=DEFAULT_MINIMUM_EXACT_COVERAGE)
    parser.add_argument(
        "--maximum-ambiguous-error-rate",
        type=float,
        default=DEFAULT_MAXIMUM_AMBIGUOUS_ERROR_RATE,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    thresholds = ValidationThresholds(
        minimum_exact_coverage=args.minimum_exact_coverage,
        maximum_ambiguous_error_rate=args.maximum_ambiguous_error_rate,
        strict=args.strict,
    )
    try:
        result = validate_regional_evidence_run(
            run_dir=args.run_dir,
            review_sample_size=args.review_sample_size,
            review_file=args.review_file,
            thresholds=thresholds,
        )
    except Exception as exc:
        print(f"validation_error={exc.__class__.__name__}:{exc}")
        return 1

    summary = result["validation_summary"]
    aggregate = summary["coverage"]["aggregate"]
    print(f"run_id={summary['source_run_id']}")
    print(f"validation_output_dir={result['validation_output_dir']}")
    print(f"classification_counts={summary['classification_counts']}")
    print(f"complete_identity_coverage={aggregate['complete_identity_coverage']}")
    print(f"final_recommendation={result['final_recommendation']}")

    blocked = result["final_recommendation"] in {
        BLOCKED_BY_DATA_INTEGRITY,
        BLOCKED_BY_LOW_COVERAGE,
    }
    if args.strict and blocked:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
