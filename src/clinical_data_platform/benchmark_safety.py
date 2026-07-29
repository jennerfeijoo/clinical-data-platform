"""Safety checks for destructive benchmark execution."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg import sql

BENCHMARK_DATA_SCHEMAS = ("audit", "clinical", "analytics")


def platform_table_counts(
    connection: psycopg.Connection[Any],
) -> dict[str, int]:
    """Count rows in every governed base table inspected by the benchmark."""
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
    """Refuse destructive benchmarking when governed tables contain any rows."""
    populated = {
        table_name: row_count
        for table_name, row_count in platform_table_counts(connection).items()
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
