from __future__ import annotations

import argparse
from pathlib import Path

from app.regional_human_judgment import (
    DEFAULT_CASES_OUTPUT_ROOT,
    DEFAULT_CASES_PER_LANGUAGE,
    DEFAULT_CASE_TYPES,
    DEFAULT_MAX_TOTAL_CASES,
    JudgmentCaseBuilderConfig,
    build_regional_judgment_cases,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build blinded multilingual human ranking judgment cases.")
    parser.add_argument("--evaluation-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--cases-per-language", type=int, default=DEFAULT_CASES_PER_LANGUAGE)
    parser.add_argument("--max-total-cases", type=int, default=DEFAULT_MAX_TOTAL_CASES)
    parser.add_argument("--case-type", action="append", default=[])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    case_types = tuple(args.case_type) if args.case_type else DEFAULT_CASE_TYPES
    try:
        result = build_regional_judgment_cases(
            evaluation_dir=args.evaluation_dir,
            output_dir=args.output_dir or (DEFAULT_CASES_OUTPUT_ROOT / args.evaluation_dir.name),
            config=JudgmentCaseBuilderConfig(
                cases_per_language=args.cases_per_language,
                max_total_cases=args.max_total_cases,
                case_types=case_types,
            ),
        )
    except Exception as exc:
        print(f"judgment_case_build_error={exc.__class__.__name__}:{exc}")
        return 1

    print(f"output_dir={result['output_dir']}")
    print(f"record_count={result['record_count']}")
    print(f"language_counts={result['language_counts']}")
    print(f"case_type_counts={result['case_type_counts']}")
    print(f"output_hashes={result['output_hashes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
