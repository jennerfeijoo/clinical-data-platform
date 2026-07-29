import csv
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
import pytest

from clinical_data_platform.database import persist_dataset_validation_outputs
from clinical_data_platform.migration import migrate_database
from clinical_data_platform.pipeline import run_dataset_validation

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIRECTORY = REPOSITORY_ROOT / "data" / "sample"


def _validate_and_load(
    connection: psycopg.Connection[Any],
    tmp_path: Path,
    dataset: str,
    source_path: Path,
    run_name: str,
):
    output_directory = tmp_path / "processed" / run_name
    raw_root = tmp_path / "raw"
    validation = run_dataset_validation(
        dataset,
        source_path,
        output_directory,
        raw_root=raw_root,
        reference_date=date(2026, 7, 29),
    )
    persistence = persist_dataset_validation_outputs(
        connection,
        dataset,
        output_directory,
        raw_root=raw_root,
    )
    return validation, persistence


def _replace_value(
    source_path: Path,
    target_path: Path,
    *,
    identity_column: str,
    identity_value: str,
    field: str,
    value: str,
) -> None:
    with source_path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None:
            raise AssertionError("Fixture must have a CSV header.")
        rows = list(reader)
        fieldnames = reader.fieldnames

    for row in rows:
        if row[identity_column] == identity_value:
            row[field] = value
            break
    else:
        raise AssertionError(f"Fixture identity not found: {identity_value}")

    with target_path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _load_prerequisites(
    connection: psycopg.Connection[Any],
    tmp_path: Path,
) -> None:
    for dataset in ("patients", "encounters"):
        _validate_and_load(
            connection,
            tmp_path,
            dataset,
            SAMPLE_DIRECTORY / f"{dataset}.csv",
            dataset,
        )


@pytest.mark.integration
def test_medications_and_procedures_are_loaded_with_expected_optional_values(
    tmp_path: Path,
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    connection = clean_database_connection
    migrate_database(connection)
    _load_prerequisites(connection, tmp_path)

    medication_validation, medication_load = _validate_and_load(
        connection,
        tmp_path,
        "medications",
        SAMPLE_DIRECTORY / "medications.csv",
        "medications",
    )
    procedure_validation, procedure_load = _validate_and_load(
        connection,
        tmp_path,
        "procedures",
        SAMPLE_DIRECTORY / "procedures.csv",
        "procedures",
    )

    assert medication_validation.rows_valid == 6
    assert medication_validation.rows_invalid == 1
    assert medication_load.records_upserted == 6
    assert procedure_validation.rows_valid == 6
    assert procedure_validation.rows_invalid == 1
    assert procedure_load.records_upserted == 6

    active_medication = connection.execute(
        """
        SELECT end_datetime, dose_value, dose_unit, route, record_sha256
        FROM clinical.medications
        WHERE medication_id = 'M002'
        """
    ).fetchone()
    procedure = connection.execute(
        """
        SELECT code_system, status, record_sha256
        FROM clinical.procedures
        WHERE procedure_id = 'PR001'
        """
    ).fetchone()

    assert active_medication is not None
    assert active_medication[0] is None
    assert active_medication[1:4] == (500.0, "mg", "ORAL")
    assert len(str(active_medication[4]).strip()) == 64
    assert procedure is not None
    assert procedure[0:2] == ("SNOMED", "COMPLETED")
    assert len(str(procedure[2]).strip()) == 64


@pytest.mark.integration
@pytest.mark.parametrize(
    ("dataset", "table", "identity_column", "identity", "field", "value", "error"),
    [
        (
            "medications",
            "medications",
            "medication_id",
            "M001",
            "status",
            "STOPPED",
            "Immutable medication conflict",
        ),
        (
            "procedures",
            "procedures",
            "procedure_id",
            "PR001",
            "status",
            "IN_PROGRESS",
            "Immutable procedure conflict",
        ),
    ],
)
def test_new_clinical_entities_preserve_duplicates_and_reject_conflicts(
    tmp_path: Path,
    clean_database_connection: psycopg.Connection[Any],
    dataset: str,
    table: str,
    identity_column: str,
    identity: str,
    field: str,
    value: str,
    error: str,
) -> None:
    connection = clean_database_connection
    migrate_database(connection)
    _load_prerequisites(connection, tmp_path)

    first, _ = _validate_and_load(
        connection,
        tmp_path,
        dataset,
        SAMPLE_DIRECTORY / f"{dataset}.csv",
        f"{dataset}-first",
    )
    _validate_and_load(
        connection,
        tmp_path,
        dataset,
        SAMPLE_DIRECTORY / f"{dataset}.csv",
        f"{dataset}-identical",
    )

    original = connection.execute(
        f"SELECT source_run_id, record_sha256 FROM clinical.{table} "
        f"WHERE {identity_column} = %s",
        (identity,),
    ).fetchone()
    assert original is not None
    assert original[0] == first.run_id

    conflicting_source = tmp_path / f"{dataset}-conflicting.csv"
    _replace_value(
        SAMPLE_DIRECTORY / f"{dataset}.csv",
        conflicting_source,
        identity_column=identity_column,
        identity_value=identity,
        field=field,
        value=value,
    )
    output_directory = tmp_path / "processed" / f"{dataset}-conflicting"
    raw_root = tmp_path / "raw"
    conflict = run_dataset_validation(
        dataset,
        conflicting_source,
        output_directory,
        raw_root=raw_root,
        reference_date=date(2026, 7, 29),
    )

    with pytest.raises(psycopg.IntegrityError, match=error):
        persist_dataset_validation_outputs(
            connection,
            dataset,
            output_directory,
            raw_root=raw_root,
        )

    preserved = connection.execute(
        f"SELECT source_run_id, record_sha256 FROM clinical.{table} "
        f"WHERE {identity_column} = %s",
        (identity,),
    ).fetchone()
    failed_run = connection.execute(
        "SELECT COUNT(*) FROM audit.pipeline_runs WHERE run_id = %s",
        (conflict.run_id,),
    ).fetchone()

    assert preserved == original
    assert failed_run == (0,)
