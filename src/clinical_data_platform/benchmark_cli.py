"""Console command for reproducible loading benchmarks."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from clinical_data_platform.benchmark import (
    BenchmarkConfiguration,
    run_loading_benchmark,
)
from clinical_data_platform.database import (
    connect_database,
    database_url_from_environment,
)
from clinical_data_platform.migration import migrate_database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clinical-data-benchmark",
        description=(
            "Compare governed PostgreSQL COPY loading with the previous "
            "psycopg executemany reference path using deterministic synthetic data."
        ),
    )
    parser.add_argument(
        "--patients",
        type=int,
        nargs="+",
        default=[250, 1000, 2500],
        help="Unique increasing patient counts to benchmark.",
    )
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/benchmarks/loading"),
    )
    parser.add_argument("--database-url", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configuration = BenchmarkConfiguration(
        patient_counts=tuple(args.patients),
        repetitions=args.repetitions,
        warmups=args.warmups,
        seed=args.seed,
    )
    database_url = args.database_url or database_url_from_environment()
    with connect_database(database_url) as connection:
        migrate_database(connection)
        artifacts = run_loading_benchmark(
            connection,
            args.output_dir,
            configuration=configuration,
        )

    print(
        "Loading benchmark completed: "
        f"patients={list(artifacts.patient_counts)}, "
        f"trials={artifacts.total_trials}, "
        f"speedups={dict(artifacts.median_speedup_by_patient_count)}"
    )
    print(f"JSON report: {artifacts.report_path}")
    print(f"Trial CSV: {artifacts.trials_csv_path}")
    print(f"Markdown summary: {artifacts.summary_markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
