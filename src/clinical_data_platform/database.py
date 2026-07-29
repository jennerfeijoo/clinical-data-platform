"""PostgreSQL persistence for validated clinical data outputs."""

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


class DatabaseConfigurationError(RuntimeError):
    """Raised when the database connection is not configured."""


class PersistenceError(RuntimeError):
    """Raised when validation outputs are incomplete or inconsistent."""


class QualityReport(TypedDict):
    """Required fields from a patient validation quality report."""

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
class PersistenceSummary:
    """Result of loading one validation run into PostgreSQL."""

    run_id: UUID
    already_loaded: bool
    patients_upserted: int
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
    """Create the clinical and audit database objects when absent."""
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
            raise PersistenceError(f"Quality report field must be a non-negative integer: {field}")

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
    observed_rows = len(valid_records) + len(invalid_records)
    if report["rows_received"] != observed_rows:
        raise PersistenceError(
            "Quality report rows_received does not match the generated CSV outputs."
        )
    if report["rows_valid"] != len(valid_records):
        raise PersistenceError("Quality report rows_valid does not match valid_patients.csv.")
    if report["rows_invalid"] != len(invalid_records):
        raise PersistenceError("Quality report rows_invalid does not match invalid_patients.csv.")
    if report["validation_errors"] != len(validation_errors):
        raise PersistenceError(
            "Quality report validation_errors does not match validation_errors.csv."
        )


def persist_patient_validation_outputs(
    connection: psycopg.Connection[Any],
    output_directory: Path,
) -> PersistenceSummary:
    """Load one validated patient run and its audit metadata transactionally."""
    report = _read_quality_report(output_directory / "quality_report.json")
    valid_records = read_csv_records(output_directory / "valid_patients.csv")
    invalid_records = read_csv_records(output_directory / "invalid_patients.csv")
    validation_errors = read_csv_records(output_directory / "validation_errors.csv")
    _validate_output_counts(report, valid_records, invalid_records, validation_errors)

    if report["dataset"] != "patients":
        raise PersistenceError(f"Unsupported dataset in quality report: {report['dataset']}")
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

    patient_values: list[tuple[object, ...]] = []
    for record in valid_records:
        death_date_text = record["death_date"].strip()
        patient_values.append(
            (
                record["patient_id"].strip(),
                record["sex_at_birth"].strip(),
                date.fromisoformat(record["birth_date"].strip()),
                date.fromisoformat(death_date_text) if death_date_text else None,
                record["source_system"].strip(),
                run_id,
                report["input_sha256"],
            )
        )

    error_values: list[tuple[object, ...]] = []
    for error in validation_errors:
        error_values.append(
            (
                run_id,
                int(error["row_number"]),
                error["patient_id"] or None,
                error["field"],
                error["rule"],
                error["message"],
                error["value"] or None,
            )
        )

    with connection.transaction():
        insert_run = connection.execute(
            """
            INSERT INTO audit.pipeline_runs (
                run_id,
                dataset_name,
                source_path,
                source_sha256,
                reference_date,
                rows_received,
                rows_valid,
                rows_invalid,
                validation_errors,
                status,
                generated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id) DO NOTHING
            """,
            (
                run_id,
                report["dataset"],
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

        if insert_run.rowcount == 0:
            return PersistenceSummary(
                run_id=run_id,
                already_loaded=True,
                patients_upserted=0,
                validation_errors_inserted=0,
            )

        if patient_values:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO clinical.patients (
                        patient_id,
                        sex_at_birth,
                        birth_date,
                        death_date,
                        source_system,
                        source_run_id,
                        source_sha256
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (patient_id) DO UPDATE SET
                        sex_at_birth = EXCLUDED.sex_at_birth,
                        birth_date = EXCLUDED.birth_date,
                        death_date = EXCLUDED.death_date,
                        source_system = EXCLUDED.source_system,
                        source_run_id = EXCLUDED.source_run_id,
                        source_sha256 = EXCLUDED.source_sha256,
                        loaded_at = CURRENT_TIMESTAMP
                    """,
                    patient_values,
                )

        if error_values:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO audit.validation_errors (
                        run_id,
                        row_number,
                        patient_id,
                        field_name,
                        rule_name,
                        message,
                        rejected_value
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    error_values,
                )

    return PersistenceSummary(
        run_id=run_id,
        already_loaded=False,
        patients_upserted=len(patient_values),
        validation_errors_inserted=len(error_values),
    )
