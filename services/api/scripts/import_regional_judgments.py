from __future__ import annotations

import argparse
from pathlib import Path

from app.regional_human_judgment import DEFAULT_REVIEWED_OUTPUT_ROOT, import_reviewed_regional_judgments


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and import completed regional ranking judgments.")
    parser.add_argument("--judgment-dir", type=Path, required=True)
    parser.add_argument("--reviewed-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = import_reviewed_regional_judgments(
            judgment_dir=args.judgment_dir,
            reviewed_csv_path=args.reviewed_csv,
            output_dir=args.output_dir or (DEFAULT_REVIEWED_OUTPUT_ROOT / args.judgment_dir.name),
        )
    except Exception as exc:
        print(f"review_import_error={exc.__class__.__name__}:{exc}")
        return 1

    print(f"output_dir={result['output_dir']}")
    print(f"reviewed_count={result['reviewed_count']}")
    print(f"reviewer_decision_counts={result['summary']['reviewer_decision_counts']}")
    print(f"reviewer_confidence_counts={result['summary']['reviewer_confidence_counts']}")
    print(f"output_hashes={result['output_hashes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
