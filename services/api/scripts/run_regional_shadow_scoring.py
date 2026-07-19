from __future__ import annotations

import argparse
from pathlib import Path

from app.cine_score_v2 import ShadowScoreWeights
from app.regional_shadow_scoring import DEFAULT_OUTPUT_ROOT, run_regional_shadow_scoring


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic offline cine-score-v2 shadow scoring.")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--language", action="append", default=[])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = run_regional_shadow_scoring(
            run_dir=args.run_dir,
            baseline_dir=args.baseline_dir,
            output_dir=args.output_dir or (DEFAULT_OUTPUT_ROOT / args.run_dir.name),
            languages=args.language,
            weights=ShadowScoreWeights(),
        )
    except Exception as exc:
        print(f"shadow_scoring_error={exc.__class__.__name__}:{exc}")
        return 1

    summary = result["summary"]
    print(f"gate_status={result['gate_status']}")
    print(f"provisional_status={result['provisional_status']}")
    print(f"activation_eligible={result['activation_eligible']}")
    print(f"allowed_languages={result['allowed_languages']}")
    print(f"output_dir={result['output_dir']}")
    print(f"movies_processed={summary['movies_processed']}")
    print(f"v2_scorable_count={summary['v2_scorable_count']}")
    print(f"unscorable_count={summary['unscorable_count']}")
    print(f"cohort_level_distribution={summary['cohort_level_distribution']}")
    print(f"fallback_distribution={summary['fallback_distribution']}")
    print(f"signal_coverage={summary['signal_coverage']}")
    print(f"v1_v2_metrics={summary['v1_v2_metrics']}")
    print(f"top_movers_up={summary['top_movers_up']}")
    print(f"top_movers_down={summary['top_movers_down']}")
    print(f"output_hashes={result['output_hashes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
