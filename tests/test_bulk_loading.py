from pathlib import Path
from typing import Any

import psycopg
import pytest

from clinical_data_platform.bulk import CopyMergePlan, copy_merge_rows, copy_rows
from clinical_data_platform.ingestion import inspect_csv_records, iter_csv_records



def test_copy_merge_plan_rejects_unsafe_column_relationships() -> None:
    with pytest.raises(ValueError, match="Conflict columns"):
        CopyMergePlan(
            schema="clinical",
            table="patients",
            columns=("patient_id", "source_system"),
            conflict_columns=("missing_id",),
            update_columns=("source_system",),
        )

    with pytest.raises(ValueError, match="cannot also be update"):
        CopyMergePlan(
            schema="clinical",
            table="patients",
            columns=("patient_id", "source_system"),
            conflict_columns=("patient_id",),
            update_columns=("patient_id", "source_system"),
        )


def test_csv_inspection_and_iteration_do_not_change_record_semantics(tmp_path: Path) -> None:
    source = tmp_path / "records.csv"
    source.write_text("id,value\n1,alpha\n2,beta\n", encoding="utf-8")

    inspection = inspect_csv_records(source)
    records = list(iter_csv_records(source))

    assert inspection.columns == ("id", "value")
    assert inspection.row_count == 2
    assert records == [
        {"id": "1", "value": "alpha"},
        {"id": "2", "value": "beta"},
    ]


@pytest.mark.integration
def test_copy_staging_merge_and_direct_copy_are_set_based(
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    connection = clean_database_connection
    plan = CopyMergePlan(
        schema="pg_temp",
        table="copy_target",
        columns=("record_id", "value"),
        conflict_columns=("record_id",),
        update_columns=("value",),
        touch_loaded_at=True,
    )

    with connection.transaction():
        connection.execute(
            """
            CREATE TEMP TABLE copy_target (
                record_id INTEGER PRIMARY KEY,
                value TEXT NOT NULL,
                loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TEMP TABLE copy_audit (
                record_id INTEGER NOT NULL,
                note TEXT NOT NULL
            );
            """,
            prepare=False,
        )

        first = copy_merge_rows(connection, plan, [(1, "alpha"), (2, "beta")])
        second = copy_merge_rows(connection, plan, [(2, "updated"), (3, "gamma")])
        audit_rows = copy_rows(
            connection,
            schema="pg_temp",
            table="copy_audit",
            columns=("record_id", "note"),
            rows=[(1, "first"), (2, "second")],
        )

        rows = connection.execute(
            "SELECT record_id, value FROM copy_target ORDER BY record_id"
        ).fetchall()
        audit = connection.execute(
            "SELECT record_id, note FROM copy_audit ORDER BY record_id"
        ).fetchall()

    assert first.rows_copied == 2
    assert first.rows_merged == 2
    assert second.rows_copied == 2
    assert second.rows_merged == 2
    assert first.staging_table != second.staging_table
    assert audit_rows == 2
    assert rows == [(1, "alpha"), (2, "updated"), (3, "gamma")]
    assert audit == [(1, "first"), (2, "second")]
