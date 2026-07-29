"""Generic PostgreSQL persistence for validated clinical datasets."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, TypedDict
from uuid import UUID

import psycopg

from clinical_data_platform.ingestion import read_csv_records
from clinical_data_platform.registry import get_dataset_definition


class DatabaseConfigurationError(RuntimeError):
    """Raised when the database connection is not configured."""


class PersistenceError(RuntimeError):
    """Raised when validation outputs are incomplete or inconsistent."""


class QualityReport(TypedDict):
    """Required fields shared by every dataset quality report."""

    run_id: str
    dataset: str
    generated_at: str
    input_path: str
    input_sha256: str
    reference_date: str
    rows_received: int
    rows_valid: int
    rows_invalid: int
    validation_errors: int
    status: str


@dataclass(frozen=True, slots=True)
class DatasetPersistenceSummary:
    """Result of loading one registered dataset into PostgreSQL."""

    run_id: UUID
    dataset: str
    already_loaded: bool
    records_upserted: int
    validation_errors_inserted: int


def database_url_from_environment() -> str:
    """Read the PostgreSQL connection URL from ``DATABASE_URL``."""
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise DatabaseConfigurationError(
            "DATABASE_URL is required, for example: "
            "postgresql://clinical_user:clinical_password@localhost:5432/clinical_data"
        )
    return database_url


def connect_database(database_url: str) -> psycopg.Connection[Any]:
    """Open a PostgreSQL connection."""
    return psycopg.connect(database_url)


def apply_schema(connection: psycopg.Connection[Any], schema_path: Path) -> None:
    """Create the clinical, audit, and analytics database objects when absent."""
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")

    schema_sql = schema_path.read_text(encoding="utf-8")
    connection.execute(schema_sql, prepare=False)
    connection.commit()


def _read_quality_report(path: Path) -> QualityReport:
    if not path.exists():
        raise FileNotFoundError(f"Quality report not found: {path}")

    with path.open(encoding="utf-8") as file:
        raw = json.load(file)

    if not isinstance(raw, dict):
        raise PersistenceError("The quality report must contain a JSON object.")

    string_fields = (
        "run_id",
        "dataset",
        "generated_at",
        "input_path",
        "input_sha256",
        "reference_date",
        "status",
    )
    integer_fields = (
        "rows_received",
        "rows_valid",
        "rows_invalid",
        "validation_errors",
    )

    for field in string_fields:
        if not isinstance(raw.get(field), str) or not raw[field]:
            raise PersistenceError(f"Quality report field must be a non-empty string: {field}")

    for field in integer_fields:
        value = raw.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise PersistenceError(
                f"Quality report field must be a non-negative integer: {field}"
            )

    return QualityReport(
        run_id=raw["run_id"],
        dataset=raw["dataset"],
        generated_at=raw["generated_at"],
        input_path=raw["input_path"],
        input_sha256=raw["input_sha256"],
        reference_date=raw["reference_date"],
        rows_received=raw["rows_received"],
        rows_valid=raw["rows_valid"],
        rows_invalid=raw["rows_invalid"],
        validation_errors=raw["validation_errors"],
        status=raw["status"],
    )


def _validate_output_counts(
    report: QualityReport,
    valid_records: list[dict[str, str]],
    invalid_records: list[dict[str, str]],
    validation_errors: list[dict[str, str]],
) -> None:
    if report["rows_received"] != len(valid_records) + len(invalid_records):
        raise PersistenceError("rows_received does not match the generated CSV outputs.")
    if report["rows_valid"] != len(valid_records):
        raise PersistenceError("rows_valid does not match the valid-record output.")
    if report["rows_invalid"] != len(invalid_records):
        raise PersistenceError("rows_invalid does not match the invalid-record output.")
    if report["validation_errors"] != len(validation_errors):
        raise PersistenceError("validation_errors does not match validation_errors.csv.")


def persist_dataset_validation_outputs(
    connection: psycopg.Connection[Any],
    dataset: str,
    output_directory: Path,
) -> DatasetPersistenceSummary:
    """Load one registered dataset and its audit metadata transactionally."""
    definition = get_dataset_definition(dataset)
    report = _read_quality_report(output_directory / "quality_report.json")
    valid_records = read_csv_records(output_directory / f"valid_{dataset}.csv")
    invalid_records = read_csv_records(output_directory / f"invalid_{dataset}.csv")
    validation_errors = read_csv_records(output_directory / "validation_errors.csv")
    _validate_output_counts(report, valid_records, invalid_records, validation_errors)

    if report["dataset"] != dataset:
        raise PersistenceError(
            f"Quality report contains {report['dataset']!r}, expected {dataset!r}."
        )
    if report["status"] != "completed":
        raise PersistenceError("Only completed validation runs can be persisted.")
    if len(report["input_sha256"]) != 64:
        raise PersistenceError("input_sha256 must contain 64 hexadecimal characters.")

    try:
        run_id = UUID(report["run_id"])
        generated_at = datetime.fromisoformat(report["generated_at"])
        reference_date = date.fromisoformat(report["reference_date"])
    except ValueError as exc:
        raise PersistenceError("The quality report contains an invalid UUID or date.") from exc

    record_values = definition.row_builder(
        valid_records,
        run_id,
        report["input_sha256"],
    )
    error_values = [
        (
            run_id,
            int(error["row_number"]),
            error["entity_id"] or None,
            error["patient_id"] or None,
            error["field"],
            error["rule"],
            error["message"],
            error["value"] or None,
        )
        for error in validation_errors
    ]

    with connection.transaction():
        inserted_run = connection.execute(
            """
            INSERT INTO audit.pipeline_runs (
                run_id, dataset_name, source_path, source_sha256,
                reference_date, rows_received, rows_valid, rows_invalid,
                validation_errors, status, generated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id) DO NOTHING
            """,
            (
                run_id,
                dataset,
                report["input_path"],
                report["input_sha256"],
                reference_date,
                report["rows_received"],
                report["rows_valid"],
                report["rows_invalid"],
                report["validation_errors"],
                report["status"],
                generated_at,
            ),
        )

        if inserted_run.rowcount == 0:
            return DatasetPersistenceSummary(run_id, dataset, True, 0, 0)

        if record_values:
            with connection.cursor() as cursor:
                cursor.executemany(definition.upsert_sql, record_values)

        if error_values:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO audit.validation_errors (
                        run_id, row_number, entity_id, patient_id,
                        field_name, rule_name, message, rejected_value
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    error_values,
                )

    return DatasetPersistenceSummary(
        run_id=run_id,
        dataset=dataset,
        already_loaded=False,
        records_upserted=len(record_values),
        validation_errors_inserted=len(error_values),
    )
