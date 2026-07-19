from __future__ import annotations

import argparse
from pathlib import Path

from app.regional_evidence_validation import (
    BLOCKED_BY_LOW_COVERAGE,
    DEFAULT_MINIMUM_EXACT_COVERAGE,
    DEFAULT_MINIMUM_COMPLETE_IDENTITY_COVERAGE,
    DEFAULT_MINIMUM_REVIEW_CONFIRMATION_RATE,
    DEFAULT_MAXIMUM_CRITICAL_WARNING_REJECTION_RATE,
    DEFAULT_MAXIMUM_UNRESOLVED_AMBIGUITY_RATE,
    DEFAULT_MINIMUM_REVIEWED_ROWS,
    DEFAULT_MINIMUM_LANGUAGE_REVIEWED_ROWS,
    BLOCKED_BY_ENTITY_RESOLUTION_QUALITY,
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
    parser.add_argument("--minimum-complete-identity-coverage", type=float, default=DEFAULT_MINIMUM_COMPLETE_IDENTITY_COVERAGE)
    parser.add_argument("--minimum-review-confirmation-rate", type=float, default=DEFAULT_MINIMUM_REVIEW_CONFIRMATION_RATE)
    parser.add_argument(
        "--maximum-critical-warning-rejection-rate",
        type=float,
        default=DEFAULT_MAXIMUM_CRITICAL_WARNING_REJECTION_RATE,
    )
    parser.add_argument(
        "--maximum-unresolved-ambiguity-rate",
        type=float,
        default=DEFAULT_MAXIMUM_UNRESOLVED_AMBIGUITY_RATE,
    )
    parser.add_argument("--minimum-reviewed-rows", type=int, default=DEFAULT_MINIMUM_REVIEWED_ROWS)
    parser.add_argument("--minimum-language-reviewed-rows", type=int, default=DEFAULT_MINIMUM_LANGUAGE_REVIEWED_ROWS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    thresholds = ValidationThresholds(
        minimum_exact_coverage=args.minimum_exact_coverage,
        minimum_complete_identity_coverage=args.minimum_complete_identity_coverage,
        minimum_review_confirmation_rate=args.minimum_review_confirmation_rate,
        maximum_critical_warning_rejection_rate=args.maximum_critical_warning_rejection_rate,
        maximum_unresolved_ambiguity_rate=args.maximum_unresolved_ambiguity_rate,
        minimum_reviewed_rows=args.minimum_reviewed_rows,
        minimum_language_reviewed_rows=args.minimum_language_reviewed_rows,
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
    print(f"review_sample_path={result['review_sample_path']}")
    print(f"classification_counts={summary['classification_counts']}")
    print(f"per_language_coverage={summary['coverage']['per_language']}")
    print(f"complete_identity_coverage={aggregate['complete_identity_coverage']}")
    print(f"review_stats={summary['review_stats']}")
    print(f"final_recommendation={result['final_recommendation']}")

    blocked = result["final_recommendation"] in {
        BLOCKED_BY_LOW_COVERAGE,
        BLOCKED_BY_ENTITY_RESOLUTION_QUALITY,
    }
    if args.strict and blocked:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
