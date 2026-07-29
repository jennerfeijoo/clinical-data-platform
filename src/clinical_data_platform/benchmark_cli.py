"""Console command for reproducible loading benchmarks."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

from clinical_data_platform.benchmark import (
    BenchmarkConfiguration,
    run_loading_benchmark,
)
from clinical_data_platform.database import (
    connect_database,
    database_url_from_environment,
)
from clinical_data_platform.migration import migrate_database

BENCHMARK_DATA_SCHEMAS = ("audit", "clinical", "analytics")


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
    parser.add_argument(
        "--repetitions",
        type=int,
        default=6,
        help="Positive even repetition count so method starting positions are balanced.",
    )
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/benchmarks/loading"),
    )
    parser.add_argument("--database-url", default=None)
    parser.add_argument(
        "--allow-destructive-reset",
        action="store_true",
        help=(
            "Confirm that the target is an isolated disposable database whose "
            "platform tables may be truncated between trials."
        ),
    )
    return parser


def _validate_balanced_repetitions(repetitions: int) -> None:
    if repetitions <= 0 or repetitions % 2 != 0:
        raise ValueError(
            "Benchmark repetitions must be a positive even integer so COPY and "
            "executemany start the same number of measured trials."
        )


def _platform_table_counts(
    connection: psycopg.Connection[Any],
) -> dict[str, int]:
    rows = connection.execute(
        """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_type = 'BASE TABLE'
          AND table_schema = ANY(%s)
        ORDER BY table_schema, table_name
        """,
        (list(BENCHMARK_DATA_SCHEMAS),),
    ).fetchall()

    counts: dict[str, int] = {}
    for schema_name, table_name in rows:
        qualified_name = f"{schema_name}.{table_name}"
        count_row = connection.execute(
            sql.SQL("SELECT COUNT(*) FROM {}").format(
                sql.Identifier(str(schema_name), str(table_name))
            )
        ).fetchone()
        if count_row is None:
            raise RuntimeError(
                f"Could not inspect benchmark target table {qualified_name}."
            )
        counts[qualified_name] = int(count_row[0])
    return counts


def assert_isolated_empty_benchmark_database(
    connection: psycopg.Connection[Any],
) -> None:
    """Refuse to benchmark when any governed data or audit table is populated."""
    populated = {
        table_name: row_count
        for table_name, row_count in _platform_table_counts(connection).items()
        if row_count > 0
    }
    if populated:
        evidence = ", ".join(
            f"{table_name}={row_count}"
            for table_name, row_count in sorted(populated.items())
        )
        raise RuntimeError(
            "Benchmark target is not empty. Use a dedicated disposable database; "
            f"refusing destructive reset because populated tables were found: {evidence}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.allow_destructive_reset:
        parser.error(
            "--allow-destructive-reset is required because the benchmark truncates "
            "platform state between trials."
        )
    try:
        _validate_balanced_repetitions(args.repetitions)
    except ValueError as exc:
        parser.error(str(exc))

    configuration = BenchmarkConfiguration(
        patient_counts=tuple(args.patients),
        repetitions=args.repetitions,
        warmups=args.warmups,
        seed=args.seed,
    )
    database_url = args.database_url or database_url_from_environment()
    with connect_database(database_url) as connection:
        migrate_database(connection)
        assert_isolated_empty_benchmark_database(connection)
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
