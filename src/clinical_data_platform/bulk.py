"""PostgreSQL COPY helpers for set-based clinical persistence."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import psycopg
from psycopg import sql


@dataclass(frozen=True, slots=True)
class CopyMergePlan:
    """Declarative target metadata for COPY-to-staging followed by a set merge."""

    schema: str
    table: str
    columns: tuple[str, ...]
    conflict_columns: tuple[str, ...]
    update_columns: tuple[str, ...]
    touch_loaded_at: bool = False

    def __post_init__(self) -> None:
        if not self.schema or not self.table:
            raise ValueError("COPY merge schema and table must be non-empty.")
        if not self.columns:
            raise ValueError("COPY merge columns must not be empty.")
        if len(self.columns) != len(set(self.columns)):
            raise ValueError("COPY merge columns must be unique.")
        column_set = set(self.columns)
        if not self.conflict_columns or not set(self.conflict_columns) <= column_set:
            raise ValueError("Conflict columns must be a non-empty subset of COPY columns.")
        if not set(self.update_columns) <= column_set:
            raise ValueError("Update columns must be a subset of COPY columns.")
        if set(self.conflict_columns) & set(self.update_columns):
            raise ValueError("Conflict columns cannot also be update columns.")


@dataclass(frozen=True, slots=True)
class CopyMergeSummary:
    """Rows transferred with COPY and affected by the target merge."""

    staging_table: str
    rows_copied: int
    rows_merged: int


def _identifier_list(names: Sequence[str]) -> sql.Composed:
    return sql.SQL(", ").join(sql.Identifier(name) for name in names)


def _copy_rows_with_cursor(
    cursor: psycopg.Cursor[Any],
    statement: sql.Composable,
    rows: Iterable[Sequence[object]],
) -> int:
    count = 0
    with cursor.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)
            count += 1
    return count


def copy_rows(
    connection: psycopg.Connection[Any],
    *,
    schema: str,
    table: str,
    columns: Sequence[str],
    rows: Iterable[Sequence[object]],
) -> int:
    """Stream typed rows directly into one PostgreSQL table with COPY."""
    if not columns:
        raise ValueError("COPY columns must not be empty.")
    statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(schema, table),
        _identifier_list(columns),
    )
    with connection.cursor() as cursor:
        return _copy_rows_with_cursor(cursor, statement, rows)


def copy_merge_rows(
    connection: psycopg.Connection[Any],
    plan: CopyMergePlan,
    rows: Iterable[Sequence[object]],
) -> CopyMergeSummary:
    """COPY rows into a temporary table, then merge them into the governed target."""
    staging_table = f"_cdp_{plan.table}_{uuid4().hex[:12]}"
    target = sql.Identifier(plan.schema, plan.table)
    staging = sql.Identifier(staging_table)
    columns = _identifier_list(plan.columns)

    create_staging = sql.SQL(
        "CREATE TEMP TABLE {} ON COMMIT DROP AS "
        "SELECT {} FROM {} WITH NO DATA"
    ).format(staging, columns, target)
    connection.execute(create_staging)

    copy_statement = sql.SQL("COPY {} ({}) FROM STDIN").format(staging, columns)
    with connection.cursor() as cursor:
        rows_copied = _copy_rows_with_cursor(cursor, copy_statement, rows)

    if rows_copied == 0:
        return CopyMergeSummary(
            staging_table=staging_table,
            rows_copied=0,
            rows_merged=0,
        )

    conflict_columns = _identifier_list(plan.conflict_columns)
    if plan.update_columns:
        assignments: list[sql.Composable] = [
            sql.SQL("{} = EXCLUDED.{}").format(
                sql.Identifier(column),
                sql.Identifier(column),
            )
            for column in plan.update_columns
        ]
        if plan.touch_loaded_at:
            assignments.append(sql.SQL("loaded_at = CURRENT_TIMESTAMP"))
        conflict_action = sql.SQL("DO UPDATE SET {}").format(
            sql.SQL(", ").join(assignments)
        )
    else:
        conflict_action = sql.SQL("DO NOTHING")

    merge_statement = sql.SQL(
        "INSERT INTO {} ({}) "
        "SELECT {} FROM {} "
        "ON CONFLICT ({}) {}"
    ).format(
        target,
        columns,
        columns,
        staging,
        conflict_columns,
        conflict_action,
    )
    with connection.cursor() as cursor:
        cursor.execute(merge_statement)
        rows_merged = cursor.rowcount

    return CopyMergeSummary(
        staging_table=staging_table,
        rows_copied=rows_copied,
        rows_merged=rows_merged,
    )
