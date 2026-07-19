from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path

from app.adapters.tmdb import TmdbAdapter
from app.core.config import get_settings
from app.regional_evidence import (
    DEFAULT_LANGUAGES,
    DEFAULT_LIMIT_PER_LANGUAGE,
    DEFAULT_OUTPUT_ROOT,
    RegionalEvidencePipeline,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a bounded local regional evidence sample.")
    parser.add_argument("--languages", default=",".join(DEFAULT_LANGUAGES))
    parser.add_argument("--limit-per-language", type=int, default=DEFAULT_LIMIT_PER_LANGUAGE)
    parser.add_argument("--national-awards-file", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args()


async def run() -> int:
    args = parse_args()
    settings = get_settings()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / run_id)
    languages = [value.strip().lower() for value in args.languages.split(",") if value.strip()]

    pipeline = RegionalEvidencePipeline(
        settings=settings,
        tmdb=TmdbAdapter(settings),
    )
    manifest = await pipeline.build(
        languages=languages,
        limit_per_language=args.limit_per_language,
        output_dir=output_dir,
        national_awards_file=args.national_awards_file,
    )
    print(f"run_id={manifest['run_id']}")
    print(f"output_dir={output_dir}")
    print(f"movies={manifest['record_counts']['movies']}")
    print(f"wikidata_matches={manifest['record_counts']['wikidata_matches']}")
    print(f"national_awards_records={manifest['record_counts']['national_awards_records']}")
    print(f"recognition_match_candidates={manifest['record_counts']['recognition_match_candidates']}")
    return 0


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
