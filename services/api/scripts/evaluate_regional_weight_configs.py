from __future__ import annotations

import argparse
from pathlib import Path

from app.regional_human_judgment import DEFAULT_WEIGHT_OUTPUT_ROOT, evaluate_regional_weight_configurations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate bounded cine-score-v2 weight candidates against reviewed regional judgments.")
    parser.add_argument("--judgment-dir", type=Path, required=True)
    parser.add_argument("--reviewed-dir", type=Path, required=True)
    parser.add_argument("--shadow-dir", type=Path, required=True)
    parser.add_argument("--evaluation-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = evaluate_regional_weight_configurations(
            judgment_dir=args.judgment_dir,
            reviewed_dir=args.reviewed_dir,
            shadow_dir=args.shadow_dir,
            evaluation_dir=args.evaluation_dir,
            output_dir=args.output_dir or (DEFAULT_WEIGHT_OUTPUT_ROOT / args.evaluation_dir.name),
        )
    except Exception as exc:
        print(f"weight_evaluation_error={exc.__class__.__name__}:{exc}")
        return 1

    print(f"output_dir={result['output_dir']}")
    print(f"recommendation={result['recommendation']['status']}")
    print(f"recommended_config_id={result['recommendation']['recommended_config_id']}")
    print(f"output_hashes={result['output_hashes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
