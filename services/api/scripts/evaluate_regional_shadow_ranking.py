from __future__ import annotations

import argparse
from pathlib import Path

from app.regional_shadow_evaluation import DEFAULT_OUTPUT_ROOT, evaluate_regional_shadow_ranking


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate deterministic offline v1/v2 shadow ranking behavior.")
    parser.add_argument("--shadow-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--judgment-file", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = evaluate_regional_shadow_ranking(
            shadow_dir=args.shadow_dir,
            output_dir=args.output_dir or (DEFAULT_OUTPUT_ROOT / args.shadow_dir.name),
            judgment_file=args.judgment_file,
        )
    except Exception as exc:
        print(f"shadow_evaluation_error={exc.__class__.__name__}:{exc}")
        return 1

    summary = result["summary"]
    diagnostics = summary["diagnostic_metrics"]
    regressions = summary["regression_counts"]
    print(f"evaluation_mode={summary['evaluation_mode']}")
    print(f"evidence_gate={summary['evidence_gate']}")
    print(f"review_status={summary['review_status']}")
    print(f"allowed_languages={summary['allowed_languages']}")
    print(f"phase_recommendation={summary['phase_recommendation']}")
    print(f"output_dir={result['output_dir']}")
    print(f"movies_evaluated={summary['movie_counts']['evaluated']}")
    print(f"v1_scorable_count={summary['movie_counts']['v1_scorable_count']}")
    print(f"v2_scorable_count={summary['movie_counts']['v2_scorable_count']}")
    print(f"blocking_regressions={regressions['blocking']}")
    print(f"warning_regressions={regressions['warning']}")
    print(f"informational_findings={regressions['informational']}")
    print(f"spearman_rank_correlation={diagnostics['spearman_rank_correlation']}")
    print(f"top_5_overlap={diagnostics['top_5_overlap']}")
    print(f"top_10_overlap={diagnostics['top_10_overlap']}")
    print(f"top_20_overlap={diagnostics['top_20_overlap']}")
    print(f"average_absolute_rank_movement={diagnostics['average_absolute_rank_movement']}")
    print(f"median_absolute_rank_movement={diagnostics['median_absolute_rank_movement']}")
    print(f"p90_absolute_rank_movement={diagnostics['p90_absolute_rank_movement']}")
    print(f"maximum_absolute_rank_movement={diagnostics['maximum_absolute_rank_movement']}")
    print(f"confidence_metrics={summary['confidence_metrics']}")
    print(f"fallback_metrics={summary['fallback_metrics']}")
    print(f"output_hashes={result['output_hashes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
